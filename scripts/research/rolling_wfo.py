"""
Rolling Walk-Forward Optimization (WFO) -- replaces the single fixed
60/20/20 split used by kalman_walkforward.py with a sliding window that
re-optimizes and re-tests repeatedly across the whole available history.

Motivation (see scripts/research/RESULTS.md experiment 19): the fixed-
split methodology's one "passing" result (XAUUSD M5, DSR 98.87-99.60%)
turned out to have a NEGATIVE validation-vs-test correlation across every
eligible config -- the config search wasn't finding a repeatable edge, it
was picking up whatever happened to fit that one test window. A single
train/val/test split can't tell a real, time-stable edge apart from a
lucky window. Rolling WFO can: it re-runs the same "pick best on the
recent past, test on the immediate future" procedure many times back to
back, so a real edge should show up as broadly consistent out-of-sample
performance across folds, while a lucky-window artifact will show up as
wildly inconsistent (or negatively autocorrelated) fold results.

Mechanics: TRAIN_DAYS of history -> pick the best config by net PnL among
configs with >= MIN_TRAIN_TRADES trades (same selection rule as
kalman_walkforward.py, just on a shorter window) -> apply that exact,
frozen config to the following TEST_DAYS of out-of-sample data -> slide
forward by STEP_DAYS (defaults to TEST_DAYS, i.e. non-overlapping test
folds) -> repeat until the data runs out. All out-of-sample trades from
every fold are then stitched together in chronological order into one
aggregate track record.

Grid is intentionally COARSER than kalman_walkforward.py's 384/192-config
grid (default 64 configs) -- this same grid search runs once per fold,
and a year of M5/M15 data can produce a dozen+ folds, so the full grid
would take hours. Widen it with --full-grid if you have the time.

Why not DSR here: DSR (as used by kalman_walkforward.py) assumes ONE
config gets selected ONCE from a grid of n_trials, then tested ONCE --
it deflates for "how likely is the best-of-n_trials result to look this
good by chance." A rolling WFO doesn't fit that shape: it selects a
(possibly different) config independently in EACH fold, and the number
that matters is the combined out-of-sample track record across all of
them, not any single fold's own trial count. An earlier version of this
script forced DSR's formula on anyway by hardcoding
sr_variance_across_trials=0.0, which silently skipped the multi-testing
penalty entirely (expected_max_sharpe() returns 0 whenever variance<=0)
-- a real fix (pooling each fold's eligible-config train Sharpes into a
variance estimate) made the number directionally usable but still only
an approximation layered onto an assumption that doesn't quite hold.

Replaced with a bootstrap confidence interval on the pooled out-of-
sample track record directly (bootstrap_expectancy_ci() below): resample
the stitched test-fold trade returns with replacement thousands of times,
recompute the mean each time, and see whether the resulting distribution
of means sits above zero. This asks the more directly relevant question
-- "is the expectancy actually realized across all these folds
distinguishable from zero" -- without needing any assumption about how
many configs were tried per fold or how their Sharpes were distributed.
Treat the per-fold PF/win-rate CONSISTENCY (are folds mostly above or
below breakeven, plotted below) as the primary signal, and the bootstrap
CI as the statistical-significance check on the aggregate.

Usage:
    python scripts/research/rolling_wfo.py --symbol XAUUSD --timeframe m5
    python scripts/research/rolling_wfo.py --symbol XAUUSD --timeframe m5 --train-days 90 --test-days 30
    python scripts/research/rolling_wfo.py --symbol EURUSD --timeframe m15 --full-grid
"""
import argparse
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.kalman_walkforward import load, run_cfg, profit_factor, PIP, ROUND_TRIP_PIPS, HMM_CALIB_BARS  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics  # noqa: E402
from analysis.strategies.kalman_mean_reversion import run_mean_reversion  # noqa: E402


def extract_trades(dset, cost, **kw):
    """Same signal generation as run_cfg(), but also returns each trade's
    (entry_idx, exit_idx, net_pnl) -- needed by monte_carlo_baseline() to
    draw a MATCHED holding-period distribution (see that function's
    docstring for why). Mirrors cir_rolling_wfo.py/garch_rolling_wfo.py's
    extract_trades() so the OU engine can be run through the same Monte
    Carlo permutation test added to this project after OU's own rolling
    WFO runs (added retroactively so OU could be compared on equal
    footing against CIR/GARCH-OU in the cross-model comparison chart)."""
    res = run_mean_reversion(dset["price_datetime"], dset["close_price"], dset["high_price"], dset["low_price"], **kw)
    trades = []
    pos, entry_price, entry_idx = 0, None, None
    for i, sig in enumerate(res["signal"]):
        if sig in ("long", "short"):
            pos = 1 if sig == "long" else -1
            entry_price, entry_idx = res["close"].iloc[i], i
        elif sig is not None and entry_price is not None:
            pnl = pos * (res["close"].iloc[i] - entry_price) - cost
            trades.append((entry_idx, i, pnl))
            pos, entry_price, entry_idx = 0, None, None
    return trades


def bootstrap_expectancy_ci(net_returns, n_boot=5000, ci=0.95, seed=0):
    """Bootstrap confidence interval on the mean of net_returns (per-trade
    expectancy), resampling with replacement. Returns the point estimate,
    the [ci_low, ci_high] interval, and p_positive = the fraction of
    bootstrap resamples whose mean was > 0 (a direct, assumption-light
    stand-in for "is this expectancy distinguishable from zero," see the
    module docstring for why this replaces DSR here)."""
    net_returns = np.asarray(net_returns, dtype=float)
    n = len(net_returns)
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        boot_means[i] = rng.choice(net_returns, size=n, replace=True).mean()
    lo = float(np.percentile(boot_means, (1 - ci) / 2 * 100))
    hi = float(np.percentile(boot_means, (1 + ci) / 2 * 100))
    p_positive = float(np.mean(boot_means > 0))
    return dict(mean=float(net_returns.mean()), ci_low=lo, ci_high=hi, ci=ci,
                p_positive=p_positive, n_boot=n_boot)


def monte_carlo_baseline(fold_durations, fold_closes, cost, n_sims=1000, seed=0):
    """Null-hypothesis benchmark: for each fold, draw the SAME NUMBER of
    trades as the real strategy made, with holding periods resampled
    (with replacement) from the real strategy's OWN duration distribution
    in that fold, but random entry bar and random direction (50/50 long/
    short) -- i.e. "what would a strategy with zero timing/direction
    skill, but the same trade frequency and holding-period profile,
    produce on this exact price data?" Repeated n_sims times; returns the
    array of simulated AGGREGATE (summed across all folds) total net P&L,
    one value per simulation -- the null distribution to compare the real
    aggregate result against. Defined here (the base rolling-WFO module)
    rather than in cir_rolling_wfo.py so OU/CIR/GARCH-OU can all import
    the same implementation without a circular import."""
    rng = np.random.default_rng(seed)
    sim_totals = np.zeros(n_sims)
    for durations, closes in zip(fold_durations, fold_closes):
        n_trades = len(durations)
        n_bars = len(closes)
        if n_trades == 0 or n_bars < 3:
            continue
        durations_arr = np.array(durations)
        for s in range(n_sims):
            total = 0.0
            for _ in range(n_trades):
                dur = int(np.clip(durations_arr[rng.integers(0, len(durations_arr))], 1, n_bars - 1))
                entry_idx = int(rng.integers(0, n_bars - dur))
                exit_idx = entry_idx + dur
                direction = 1 if rng.random() < 0.5 else -1
                total += direction * (closes[exit_idx] - closes[entry_idx]) - cost
            sim_totals[s] += total
    return sim_totals


def build_coarse_grid(cost, full=False):
    calib_windows = (40, 60, 80, 120, 160, 200, 240, 320) if full else (40, 80, 120, 200)
    ks = (1.8, 2.2)
    qr_combos = ((1.0, 1.0), (2.0, 0.5), (1.0, 0.5), (2.0, 1.0))
    tau_fracs = (1.0, 1.5, None) if full else (1.0, None)
    grid = []
    for calib_window in calib_windows:
        for k in ks:
            for q_mult, obs_noise_scale in qr_combos:
                for tau_frac in tau_fracs:
                    grid.append(dict(
                        calib_window=calib_window, recalib_every=5,
                        obs_noise_scale=obs_noise_scale, q_mult=q_mult, k=k,
                        z_stop=k + 1.0, half_life_mult=2.0, trend_aware=False,
                        hmm_calib_bars=HMM_CALIB_BARS, hmm_block_states=(2,),
                        tau_threshold=(calib_window * tau_frac) if tau_frac else None,
                        spread=cost, friction_hurdle_mult=2.5,
                    ))
    return grid


def make_folds(df, train_days, test_days, step_days):
    start = df["price_datetime"].min()
    end = df["price_datetime"].max()
    folds = []
    train_start = start
    while True:
        train_end = train_start + pd.Timedelta(days=train_days)
        test_end = train_end + pd.Timedelta(days=test_days)
        if test_end > end:
            break
        train_df = df[(df["price_datetime"] >= train_start) & (df["price_datetime"] < train_end)].reset_index(drop=True)
        test_df = df[(df["price_datetime"] >= train_end) & (df["price_datetime"] < test_end)].reset_index(drop=True)
        folds.append((train_start, train_end, test_end, train_df, test_df))
        train_start += pd.Timedelta(days=step_days)
    return folds


def run_fold(train_df, test_df, cost, grid, min_train_trades):
    results = []
    for kw in grid:
        net = run_cfg(train_df, cost, **kw)
        n = len(net)
        if n >= min_train_trades:
            results.append((net.sum(), profit_factor(net), n, kw))
    if not results:
        return None
    results.sort(reverse=True, key=lambda r: r[0])
    best_kw = results[0][3]
    train_net, train_pf, train_n = results[0][0], results[0][1], results[0][2]
    test_trades = extract_trades(test_df, cost, **best_kw)
    test_net = np.array([t[2] for t in test_trades])
    test_durations = [t[1] - t[0] for t in test_trades]
    return dict(best_kw=best_kw, train_net=train_net, train_pf=train_pf, train_n=train_n,
                test_net=test_net, test_durations=test_durations)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="m5")
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--step-days", type=int, default=None, help="default = test-days (non-overlapping folds)")
    parser.add_argument("--min-train-trades", type=int, default=10)
    parser.add_argument("--full-grid", action="store_true", help="use the same dense grid as kalman_walkforward.py instead of the coarse default")
    args = parser.parse_args()
    step_days = args.step_days or args.test_days

    symbol, table = args.symbol, args.timeframe
    df = load(symbol, table)
    cost = ROUND_TRIP_PIPS * PIP[symbol]
    grid = build_coarse_grid(cost, full=args.full_grid)
    folds = make_folds(df, args.train_days, args.test_days, step_days)

    print(f"=== {symbol} {table}: Rolling WFO, train={args.train_days}d test={args.test_days}d step={step_days}d ===")
    print(f"  {len(folds)} folds, {len(grid)} configs/fold")
    if not folds:
        print("  not enough history for even one fold -- widen the date range or shrink --train-days/--test-days")
        return

    fold_records = []
    t0 = time.time()
    for i, (tr_start, tr_end, te_end, train_df, test_df) in enumerate(folds):
        res = run_fold(train_df, test_df, cost, grid, args.min_train_trades)
        if res is None:
            print(f"  fold {i+1}/{len(folds)} [{tr_start.date()} -> {tr_end.date()} -> {te_end.date()}]: "
                  f"no config reached {args.min_train_trades} trades on train, skipped")
            continue
        tm = trade_metrics(res["test_net"])
        fold_records.append(dict(fold=i, tr_start=tr_start, tr_end=tr_end, te_end=te_end, **res, test_metrics=tm))
        pf_disp = f"{tm['profit_factor']:.2f}" if tm["profit_factor"] is not None else "-"
        print(f"  fold {i+1}/{len(folds)} [{tr_start.date()} -> {tr_end.date()} -> {te_end.date()}]: "
              f"train_pf={res['train_pf']:.2f} (n={res['train_n']}) -> "
              f"test n={tm['n_trades']} PF={pf_disp} win={tm['win_rate']}")
    print(f"  done in {time.time()-t0:.1f}s")

    if not fold_records:
        print("  no fold produced a usable config -- nothing to aggregate")
        return

    all_test_net = np.concatenate([r["test_net"] for r in fold_records if len(r["test_net"])])
    agg_tm = trade_metrics(all_test_net)
    boot = bootstrap_expectancy_ci(all_test_net)

    pfs = [r["test_metrics"]["profit_factor"] for r in fold_records if r["test_metrics"]["profit_factor"] is not None]
    n_folds_profitable = sum(1 for pf in pfs if pf >= 1.0)

    print("\n" + "=" * 90)
    print(f"AGGREGATE (all {len(fold_records)} out-of-sample folds stitched together, chronological)")
    print("=" * 90)
    print(f"  total n={agg_tm['n_trades']}  win_rate={agg_tm['win_rate']}  PF={agg_tm['profit_factor']}  "
          f"expectancy={agg_tm['expectancy_r']}  maxDD={agg_tm['max_drawdown_r']}")
    print(f"  Bootstrap {int(boot['ci']*100)}% CI on expectancy (n_boot={boot['n_boot']}): "
          f"mean={boot['mean']:.5f}  CI=[{boot['ci_low']:.5f}, {boot['ci_high']:.5f}]  "
          f"P(mean>0)={boot['p_positive']:.3f}")
    print(f"  -> {'CI entirely above zero: expectancy is statistically distinguishable from zero' if boot['ci_low'] > 0 else 'CI includes/is below zero: NOT statistically distinguishable from zero -- could be luck'}")
    print(f"  folds with PF>=1.0: {n_folds_profitable}/{len(pfs)} "
          f"({100*n_folds_profitable/len(pfs):.0f}%) -- consistency matters as much as the CI above")

    # Monte Carlo random-entry baseline (same test added later for CIR/GARCH-OU,
    # run here too so OU is comparable on equal footing -- see extract_trades()).
    fold_durations = [r["test_durations"] for r in fold_records]
    fold_closes = [folds[r["fold"]][4]["close_price"].to_numpy() for r in fold_records]
    real_total = float(all_test_net.sum())
    n_sims = 1000
    t_mc = time.time()
    sim_totals = monte_carlo_baseline(fold_durations, fold_closes, cost, n_sims=n_sims)
    percentile = float(np.mean(sim_totals < real_total))
    print(f"\n  Monte Carlo random-entry baseline (n_sims={n_sims}, done in {time.time()-t_mc:.1f}s):")
    print(f"    real aggregate net PnL = {real_total:.2f}")
    print(f"    random baseline: mean={sim_totals.mean():.2f}  std={sim_totals.std():.2f}")
    print(f"    real result exceeds {percentile*100:.1f}% of random-entry simulations "
          f"({'PASSES' if percentile >= 0.95 else 'does NOT pass'} the >=95th-percentile bar)")

    out_path = ROOT / "scripts" / "research" / "plots" / "ou" / f"rolling_wfo_{symbol}_{table}.png"
    fig, (ax_eq, ax_pf) = plt.subplots(2, 1, figsize=(11, 8), height_ratios=(1.3, 1))

    equity = np.cumsum(all_test_net)
    ax_eq.plot(equity, color="#3b6fa0", linewidth=1.3)
    ax_eq.axhline(0, color="#999999", linewidth=0.8)
    ax_eq.set_title(f"{symbol} {table} -- Rolling WFO out-of-sample equity curve "
                     f"({len(fold_records)} folds stitched, train={args.train_days}d/test={args.test_days}d)")
    ax_eq.set_xlabel("trade #  (chronological, across all folds)")
    ax_eq.set_ylabel("cumulative net PnL")

    fold_pfs = [min(r["test_metrics"]["profit_factor"], 5.0) if r["test_metrics"]["profit_factor"] is not None else 0.0
                for r in fold_records]
    colors = ["#2e8b57" if pf >= 1.0 else "#c0392b" for pf in fold_pfs]
    ax_pf.bar(range(len(fold_pfs)), fold_pfs, color=colors)
    ax_pf.axhline(1.0, color="#333333", linewidth=0.8, linestyle="--")
    ax_pf.set_title("Per-fold test PF (green >= 1.0 = profitable fold, red < 1.0, capped at 5.0 for display)")
    ax_pf.set_xlabel("fold #")
    ax_pf.set_ylabel("PF")

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    print(f"\n  saved equity curve + per-fold PF plot -> {out_path}")


if __name__ == "__main__":
    main()
