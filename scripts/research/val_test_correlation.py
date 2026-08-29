"""
Diagnoses the "validation weak/breakeven, test strong" pattern flagged in
scripts/research/RESULTS.md (recurring since experiment 8, confirmed again
in experiment 18 for XAUUSD M5): every config that has ever "passed" DSR>95%
had a barely-profitable or slightly-losing validation result (PF around
0.95-1.00) before turning into a strong test result. That's consistent with
either (a) a real edge that validation's shorter/different window just
under-samples, or (b) validation-selection not actually finding anything --
the winning config's good test result is luck, uncorrelated with how it did
on validation.

This script tells the two apart: it evaluates EVERY eligible (n>=15 trades
on validation) config from the grid on BOTH validation and test, then
reports the rank correlation between validation performance and test
performance across that whole set. If validation performance predicts test
performance (positive, meaningful correlation), the walk-forward split is
doing its job. If correlation is near zero or negative, validation
performance carries no information about test performance for this
symbol/timeframe -- the "winner" found by kalman_walkforward.py is
statistically indistinguishable from a random pick among eligible configs,
regardless of what its own DSR says.

Usage:
    python scripts/research/val_test_correlation.py --symbol XAUUSD --timeframe m5
    python scripts/research/val_test_correlation.py --symbol XAUUSD --timeframe m5 --trend-aware-grid
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

from scripts.research.kalman_walkforward import (  # noqa: E402
    load, split_60_20_20, run_cfg, profit_factor, build_grid, PIP, ROUND_TRIP_PIPS, MIN_VAL_TRADES,
)


def spearman(x, y):
    """Spearman rank correlation, no scipy dependency."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    return float(np.corrcoef(rx, ry)[0, 1])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="m5")
    parser.add_argument("--trend-aware-grid", action="store_true")
    args = parser.parse_args()

    symbol, table = args.symbol, args.timeframe
    df = load(symbol, table)
    train, val, test = split_60_20_20(df)
    cost = ROUND_TRIP_PIPS * PIP[symbol]
    grid = build_grid(cost, trend_aware_grid=args.trend_aware_grid)

    print(f"=== {symbol} {table}: {len(grid)} configs, evaluating on VAL and TEST for every eligible one ===")
    t0 = time.time()
    rows = []
    for kw in grid:
        val_net = run_cfg(val, cost, **kw)
        n_val = len(val_net)
        if n_val < MIN_VAL_TRADES:
            continue
        test_net = run_cfg(test, cost, **kw)
        rows.append(dict(
            kw=kw,
            val_n=n_val, val_pf=profit_factor(val_net), val_net_sum=float(val_net.sum()),
            test_n=len(test_net), test_pf=profit_factor(test_net), test_net_sum=float(test_net.sum()),
        ))
    print(f"  done in {time.time()-t0:.1f}s -- {len(rows)} eligible configs evaluated on both splits")

    if len(rows) < 5:
        print("  too few eligible configs to compute a meaningful correlation")
        return

    val_pnl = [r["val_net_sum"] for r in rows]
    test_pnl = [r["test_net_sum"] for r in rows]
    val_pf = [min(r["val_pf"], 10.0) for r in rows]   # cap inf/extreme PF so it doesn't dominate rank ties oddly
    test_pf = [min(r["test_pf"], 10.0) for r in rows]

    rho_pnl = spearman(val_pnl, test_pnl)
    rho_pf = spearman(val_pf, test_pf)
    pearson_pnl = float(np.corrcoef(val_pnl, test_pnl)[0, 1])

    print(f"\n  Spearman rank correlation, validation net PnL vs test net PnL : {rho_pnl:+.3f}")
    print(f"  Spearman rank correlation, validation PF vs test PF           : {rho_pf:+.3f}")
    print(f"  Pearson correlation, validation net PnL vs test net PnL       : {pearson_pnl:+.3f}")
    print("  (near 0 or negative = validation performance carries no information about test performance;")
    print("   the grid's 'winner' would be statistically indistinguishable from a random eligible config)")

    rows.sort(key=lambda r: r["val_net_sum"], reverse=True)
    print(f"\n  top 10 by VALIDATION net PnL -- how did they do on TEST?")
    print(f"  {'val_net':<10}{'val_pf':<8}{'val_n':<7}{'test_net':<10}{'test_pf':<8}{'test_n':<7}")
    for r in rows[:10]:
        print(f"  {r['val_net_sum']:<10.2f}{r['val_pf']:<8.2f}{r['val_n']:<7}"
              f"{r['test_net_sum']:<10.2f}{r['test_pf']:<8.2f}{r['test_n']:<7}")

    out_path = ROOT / "scripts" / "research" / "plots" / "other" / f"val_test_scatter_{symbol}_{table}.png"
    fig = plt.figure(figsize=(12, 5))
    gs = fig.add_gridspec(2, 2, width_ratios=(2, 1))

    ax_scatter = fig.add_subplot(gs[:, 0])
    ax_scatter.scatter(val_pnl, test_pnl, alpha=0.6, s=28, color="#3b6fa0", edgecolors="none")
    ax_scatter.axhline(0, color="#999999", linewidth=0.8)
    ax_scatter.axvline(0, color="#999999", linewidth=0.8)
    if np.std(val_pnl) > 0:
        b, a = np.polyfit(val_pnl, test_pnl, 1)
        xs = np.linspace(min(val_pnl), max(val_pnl), 50)
        ax_scatter.plot(xs, b * xs + a, color="#c0392b", linewidth=1.5, label="linear fit")
        ax_scatter.legend(loc="best", fontsize=9)
    ax_scatter.set_xlabel("Validation net PnL (per config)")
    ax_scatter.set_ylabel("Test net PnL (per config)")
    ax_scatter.set_title(f"{symbol} {table} -- val vs test across {len(rows)} eligible configs\n"
                          f"Spearman rho = {rho_pnl:+.3f}")

    ax_val_dist = fig.add_subplot(gs[0, 1])
    ax_val_dist.hist(val_pnl, bins=20, color="#3b6fa0", alpha=0.8)
    ax_val_dist.axvline(0, color="#999999", linewidth=0.8)
    ax_val_dist.set_title("Distribution: validation net PnL")
    ax_val_dist.set_ylabel("count")

    ax_test_dist = fig.add_subplot(gs[1, 1])
    ax_test_dist.hist(test_pnl, bins=20, color="#c0392b", alpha=0.8)
    ax_test_dist.axvline(0, color="#999999", linewidth=0.8)
    ax_test_dist.set_title("Distribution: test net PnL")
    ax_test_dist.set_xlabel("net PnL")
    ax_test_dist.set_ylabel("count")

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    print(f"\n  saved scatter + distribution plot -> {out_path}")


if __name__ == "__main__":
    main()
