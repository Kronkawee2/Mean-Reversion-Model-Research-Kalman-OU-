"""
NDX100 Long-Only, Drift-Aware Kalman/OU walk-forward evaluation -- the
pure-Quant Guild-methodology version (no Wyckoff/technical-analysis
conditions), per the revised spec: asymmetric Buy-Only bias plus a
2D state-space (level + trend-drift) Kalman filter instead of the static-
anchor one, to address NDX100's trend-dominant behavior mathematically
rather than with a discretionary pattern filter.

Formula note: the spec's 2D state-space [mu_t; beta_t] with F=[[1,1],[0,1]]
IS mathematically what analysis/strategies/kalman_mean_reversion.py's
`trend_aware` flag already implements, just via a cheaper realization --
instead of carrying a full 2-state covariance and its own process noise
on beta (which needs an extra free parameter to tune, worsening the DSR
multiple-testing penalty for no evidence it's needed -- see RESULTS.md
experiment 16's conclusion), mu_velocity (beta) is a single OLS slope
re-estimated at the same cadence as phi/mu/sigma and then advanced
deterministically each bar. This script does NOT hand-pick trend_aware
on -- it's included as a grid dimension (like k and tau) so the
validation split decides per timeframe whether the drift-aware anchor
actually helps, rather than assuming it does.

Side="long_only" (never shorts, see kalman_mean_reversion.py's `side`
param), k in {2.0, 2.8} swept per the spec's stated entry range,
z_stop=3.5 and half_life_mult=2.0 (2*half-life) fixed per spec,
friction_hurdle_mult=2.5 fixed, HMM regime filter on (blocks HIGH
volatility only -- the HMM here is volatility-based, not directional, so
it cannot distinguish "high vol downtrend" from "high vol uptrend" the
way the spec's regime condition implies; this is the same limitation
noted throughout RESULTS.md, not something new to this script).

Cost: 1.0 pip round-turn (NDX100 = 1.0 index point), per this
experiment's brief -- NOT the 1.2 pip used by kalman_walkforward.py's
general grid.

Usage:
    python scripts/research/ndx100_long_only_drift.py
    python scripts/research/ndx100_long_only_drift.py --timeframes m15,h1
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.research.kalman_walkforward import load, split_60_20_20, run_cfg, profit_factor, PIP, HMM_CALIB_BARS  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics, deflated_sharpe_ratio, sharpe_ratio  # noqa: E402

SYMBOL = "NDX100"
SPREAD_PIPS = 1.0  # round-turn, this experiment's brief
MIN_VAL_TRADES = 15

CALIB_WINDOWS = (40, 60, 80, 120, 160, 240)
QR_COMBOS = ((1.0, 1.0), (2.0, 0.5), (1.0, 0.5), (2.0, 1.0))
TAU_FRACS = (1.0, 1.5, None)
K_VALUES = (2.0, 2.8)
TREND_AWARE = (False, True)


def build_grid():
    grid = []
    for calib_window in CALIB_WINDOWS:
        for q_mult, obs_noise_scale in QR_COMBOS:
            for tau_frac in TAU_FRACS:
                for k in K_VALUES:
                    for trend_aware in TREND_AWARE:
                        grid.append(dict(
                            calib_window=calib_window, recalib_every=5,
                            obs_noise_scale=obs_noise_scale, q_mult=q_mult,
                            k=k, z_stop=3.5, half_life_mult=2.0,
                            side="long_only", trend_aware=trend_aware,
                            hmm_calib_bars=HMM_CALIB_BARS, hmm_block_states=(2,),
                            tau_threshold=(calib_window * tau_frac) if tau_frac else None,
                            spread=SPREAD_PIPS * PIP[SYMBOL], friction_hurdle_mult=2.5,
                        ))
    return grid


def evaluate(table):
    df = load(SYMBOL, table)
    train, val, test = split_60_20_20(df)
    cost = SPREAD_PIPS * PIP[SYMBOL]
    days = {
        "val": (val["price_datetime"].max() - val["price_datetime"].min()).days,
        "test": (test["price_datetime"].max() - test["price_datetime"].min()).days,
    }
    grid = build_grid()
    print(f"=== NDX100 {table} [long-only, drift-aware grid]: val={len(val)} ({days['val']}d) "
          f"test={len(test)} ({days['test']}d), grid={len(grid)} configs ===")

    t0 = time.time()
    results = []
    for kw in grid:
        net = run_cfg(val, cost, **kw)
        n = len(net)
        pf = profit_factor(net) if n else 0.0
        eligible = n >= MIN_VAL_TRADES
        results.append((net.sum() if eligible else -1e18, pf, n, kw, eligible))
    results.sort(reverse=True, key=lambda r: r[0])
    n_eligible = sum(1 for r in results if r[4])
    print(f"  validation grid done in {time.time()-t0:.1f}s ({n_eligible}/{len(grid)} eligible, n>={MIN_VAL_TRADES})")
    for total, pf, n, kw, eligible in results[:5]:
        wk = n / days["val"] * 7 if days["val"] else 0
        print(f"    net={total:.2f} PF={pf:.2f} n={n} ({wk:.2f}/wk) eligible={eligible} "
              f"calib={kw['calib_window']} k={kw['k']} q_mult={kw['q_mult']} obs_noise={kw['obs_noise_scale']} "
              f"tau={kw['tau_threshold']} trend_aware={kw['trend_aware']}")

    if not results[0][4]:
        print(f"  WARNING: no config reached {MIN_VAL_TRADES} trades on validation -- falling back to highest-n.")
        results.sort(reverse=True, key=lambda r: r[2])
    best_kw = results[0][3]
    net_test = run_cfg(test, cost, **best_kw)
    tm = trade_metrics(net_test)

    eligible_results = [r for r in results if r[4]]
    sharpes = np.array([sharpe_ratio(run_cfg(val, cost, **r[3])) for r in eligible_results[:20] if len(run_cfg(val, cost, **r[3])) >= 2])
    sr_var = float(sharpes.var(ddof=1)) if len(sharpes) >= 2 else 0.0
    dsr = deflated_sharpe_ratio(net_test, n_trials=len(grid), sr_variance_across_trials=sr_var)

    wk_test = tm["n_trades"] / days["test"] * 7 if days["test"] and tm["n_trades"] else 0
    print(f"  >>> TEST: calib={best_kw['calib_window']} k={best_kw['k']} trend_aware={best_kw['trend_aware']} "
          f"tau={best_kw['tau_threshold']}")
    print(f"      n={tm['n_trades']} ({wk_test:.2f}/wk) win_rate={tm['win_rate']} "
          f"PF={tm['profit_factor']} expectancy={tm['expectancy_r']} maxDD={tm['max_drawdown_r']} "
          f"DSR={dsr['dsr']}")
    return {
        "table": table, "best_config": best_kw,
        "test_n": tm["n_trades"], "test_weekly": wk_test, "test_win_rate": tm["win_rate"],
        "test_pf": tm["profit_factor"], "test_expectancy": tm["expectancy_r"],
        "test_maxdd": tm["max_drawdown_r"], "test_dsr": dsr["dsr"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframes", default="m5,m15,h1", help="comma-separated subset of m5,m15,h1")
    args = parser.parse_args()
    tables = [t.strip() for t in args.timeframes.split(",")]

    summary = [evaluate(table) for table in tables]

    print("=" * 100)
    print("SUMMARY -- NDX100 Long-Only, Drift-Aware, target PF>1.2, DSR>0.95")
    print("=" * 100)
    print(f"{'TF':<6}{'n(test)':<9}{'per/wk':<9}{'win%':<8}{'PF':<8}{'maxDD':<10}{'DSR':<8}")
    for s in summary:
        wr = f"{s['test_win_rate']*100:.1f}" if s["test_win_rate"] is not None else "-"
        pf = f"{s['test_pf']:.2f}" if s["test_pf"] is not None else "-"
        print(f"{s['table']:<6}{s['test_n']:<9}{s['test_weekly']:<9.2f}{wr:<8}{pf:<8}{s['test_maxdd']:<10.2f}{s['test_dsr']:<8.4f}")


if __name__ == "__main__":
    main()
