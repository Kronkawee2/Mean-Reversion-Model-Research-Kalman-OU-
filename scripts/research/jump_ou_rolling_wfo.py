"""
Rolling Walk-Forward Optimization for the jump-diffusion OU engine
(analysis/strategies/jump_ou_mean_reversion.py) -- the fourth math-derived
model tried after OU, CIR, and GARCH-OU (RESULTS.md experiment 19-32: none
cleared a validated, window-robust edge). Same methodology as
rolling_wfo.py/cir_rolling_wfo.py/garch_rolling_wfo.py (same fold-making,
Bootstrap CI, Monte Carlo random-entry baseline).

Usage:
    python scripts/research/jump_ou_rolling_wfo.py --symbol XAUUSD --timeframe m5
"""
import argparse
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.kalman_walkforward import load, sim_pnl, profit_factor, PIP, ROUND_TRIP_PIPS, HMM_CALIB_BARS  # noqa: E402
from scripts.research.rolling_wfo import make_folds, bootstrap_expectancy_ci, monte_carlo_baseline  # noqa: E402
from analysis.strategies.jump_ou_mean_reversion import run_jump_ou_mean_reversion  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics  # noqa: E402


def run_cfg(dset, cost, **kw):
    res = run_jump_ou_mean_reversion(dset["price_datetime"], dset["close_price"], dset["high_price"], dset["low_price"], **kw)
    return sim_pnl(res) - cost


def extract_trades(dset, cost, **kw):
    res = run_jump_ou_mean_reversion(dset["price_datetime"], dset["close_price"], dset["high_price"], dset["low_price"], **kw)
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


def build_grid():
    grid = []
    for calib_window in (40, 60, 80, 120):
        for k in (1.8, 2.2):
            for jump_z in (3.0, 3.5, 4.0):
                for tau_frac in (1.0, None):
                    grid.append(dict(
                        calib_window=calib_window, recalib_every=5,
                        obs_noise_scale=1.0, q_mult=1.0, k=k, jump_z=jump_z,
                        z_stop=k + 1.0, half_life_mult=2.0,
                        hmm_calib_bars=HMM_CALIB_BARS, hmm_block_states=(2,),
                        tau_threshold=(calib_window * tau_frac) if tau_frac else None,
                        friction_hurdle_mult=2.5,
                    ))
    return grid


def run_fold(train_df, test_df, cost, grid, min_train_trades):
    results = []
    for kw in grid:
        net = run_cfg(train_df, cost, spread=cost, **kw)
        n = len(net)
        if n >= min_train_trades:
            results.append((net.sum(), profit_factor(net), n, kw))
    if not results:
        return None
    results.sort(reverse=True, key=lambda r: r[0])
    best_kw = results[0][3]
    train_net, train_pf, train_n = results[0][0], results[0][1], results[0][2]
    test_trades = extract_trades(test_df, cost, spread=cost, **best_kw)
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
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--min-train-trades", type=int, default=10)
    args = parser.parse_args()
    step_days = args.step_days or args.test_days

    symbol, table = args.symbol, args.timeframe
    df = load(symbol, table)
    cost = ROUND_TRIP_PIPS * PIP[symbol]
    grid = build_grid()
    folds = make_folds(df, args.train_days, args.test_days, step_days)

    print(f"=== {symbol} {table}: Jump-Diffusion OU Rolling WFO, train={args.train_days}d test={args.test_days}d step={step_days}d ===")
    print(f"  {len(folds)} folds, {len(grid)} configs/fold")
    if not folds:
        print("  not enough history for even one fold")
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
        kw = res["best_kw"]
        print(f"  fold {i+1}/{len(folds)} [{tr_start.date()} -> {tr_end.date()} -> {te_end.date()}]: "
              f"calib={kw['calib_window']} k={kw['k']} jump_z={kw['jump_z']} train_pf={res['train_pf']:.2f} (n={res['train_n']}) -> "
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
    print(f"  -> {'CI entirely above zero: statistically significant' if boot['ci_low'] > 0 else 'CI includes/below zero: NOT statistically significant'}")
    print(f"  folds with PF>=1.0: {n_folds_profitable}/{len(pfs)} ({100*n_folds_profitable/len(pfs):.0f}%)")

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

    out_path = ROOT / "scripts" / "research" / "plots" / "jump_ou" / f"jump_ou_rolling_wfo_{symbol}_{table}.png"
    fig, (ax_eq, ax_pf) = plt.subplots(2, 1, figsize=(11, 8), height_ratios=(1.3, 1))
    equity = np.cumsum(all_test_net)
    ax_eq.plot(equity, color="#3b6fa0", linewidth=1.3)
    ax_eq.axhline(0, color="#999999", linewidth=0.8)
    ax_eq.set_title(f"{symbol} {table} -- Jump-Diffusion OU Rolling WFO out-of-sample equity curve ({len(fold_records)} folds)")
    ax_eq.set_xlabel("trade #")
    ax_eq.set_ylabel("cumulative net PnL")
    fold_pfs = [min(r["test_metrics"]["profit_factor"], 5.0) if r["test_metrics"]["profit_factor"] is not None else 0.0
                for r in fold_records]
    colors = ["#2e8b57" if pf >= 1.0 else "#c0392b" for pf in fold_pfs]
    ax_pf.bar(range(len(fold_pfs)), fold_pfs, color=colors)
    ax_pf.axhline(1.0, color="#333333", linewidth=0.8, linestyle="--")
    ax_pf.set_title("Per-fold test PF (green >= 1.0, capped at 5.0)")
    ax_pf.set_xlabel("fold #")
    ax_pf.set_ylabel("PF")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    print(f"\n  saved equity curve + per-fold PF plot -> {out_path}")


if __name__ == "__main__":
    main()
