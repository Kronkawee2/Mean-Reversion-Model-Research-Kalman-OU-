"""
Rolling Walk-Forward Optimization for the Donchian breakout trend-
following engine (analysis/strategies/trend_following.py), mirroring
rolling_wfo.py's methodology exactly (same fold-making, same bootstrap
significance check on the pooled out-of-sample track record) but pointed
at the opposite strategy family: instead of fading deviations from a
rolling mean (Kalman/OU), this buys/sells breakouts and bets the move
continues.

Motivation: every symbol/timeframe tested for the Kalman/OU mean-
reversion engine failed rolling WFO (see RESULTS.md experiment 22) -- 5
combinations, none with a bootstrap CI clear of zero. NDX100 in
particular was flagged as looking trend-dominant (waterfall drawdowns,
non-stationary trade counts under mean-reversion), i.e. structurally the
wrong model family. This script tests the opposite hypothesis on all
three symbols using the same rigorous methodology, rather than assuming
which asset "should" suit which model family.

Usage:
    python scripts/research/trend_rolling_wfo.py --symbol NDX100 --timeframe m15
    python scripts/research/trend_rolling_wfo.py --symbol XAUUSD --timeframe m5 --train-days 90 --test-days 30
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

from scripts.research.kalman_walkforward import load, sim_pnl, profit_factor, PIP, ROUND_TRIP_PIPS  # noqa: E402
from scripts.research.rolling_wfo import make_folds, bootstrap_expectancy_ci  # noqa: E402
from analysis.strategies.trend_following import run_trend_following  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics  # noqa: E402


def run_cfg(dset, cost, **kw):
    res = run_trend_following(dset["price_datetime"], dset["close_price"], dset["high_price"], dset["low_price"], **kw)
    return sim_pnl(res) - cost


def build_grid(side="both"):
    # (entry_window, exit_window) pairs -- entry always wider than exit,
    # the classic Turtle two-window shape (wide filter to enter, narrower
    # trigger to exit once the move reverses).
    windows = [(20, 10), (40, 20), (55, 20), (80, 40), (120, 40)]
    trend_filters = (None, 100, 200)
    atr_stops = (None, 2.5)
    grid = []
    for entry_window, exit_window in windows:
        for trend_filter_ema in trend_filters:
            for atr_stop_mult in atr_stops:
                grid.append(dict(
                    entry_window=entry_window, exit_window=exit_window,
                    trend_filter_ema=trend_filter_ema, atr_stop_mult=atr_stop_mult,
                    side=side,
                ))
    return grid


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
    test_net = run_cfg(test_df, cost, **best_kw)
    return dict(best_kw=best_kw, train_net=train_net, train_pf=train_pf, train_n=train_n, test_net=test_net)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="NDX100")
    parser.add_argument("--timeframe", default="m15")
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=30)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--min-train-trades", type=int, default=10)
    parser.add_argument("--side", default="both", choices=["both", "long_only", "short_only"])
    args = parser.parse_args()
    step_days = args.step_days or args.test_days

    symbol, table = args.symbol, args.timeframe
    df = load(symbol, table)
    cost = ROUND_TRIP_PIPS * PIP[symbol]
    grid = build_grid(side=args.side)
    folds = make_folds(df, args.train_days, args.test_days, step_days)

    print(f"=== {symbol} {table}: Trend-Following Rolling WFO, train={args.train_days}d test={args.test_days}d step={step_days}d side={args.side} ===")
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

    out_path = ROOT / "scripts" / "research" / "plots" / "momentum" / f"trend_rolling_wfo_{symbol}_{table}.png"
    fig, (ax_eq, ax_pf) = plt.subplots(2, 1, figsize=(11, 8), height_ratios=(1.3, 1))

    equity = np.cumsum(all_test_net)
    ax_eq.plot(equity, color="#3b6fa0", linewidth=1.3)
    ax_eq.axhline(0, color="#999999", linewidth=0.8)
    ax_eq.set_title(f"{symbol} {table} -- Trend-Following Rolling WFO out-of-sample equity curve "
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
