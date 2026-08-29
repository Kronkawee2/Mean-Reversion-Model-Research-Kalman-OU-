"""
Train / Validation / Test walk-forward evaluation of the Kalman OU mean-
reversion strategy (analysis/strategies/kalman_mean_reversion.py) across
M5, M15, and H1, per the spec: 60% train (nothing tuned here -- calibration
itself is already rolling/online inside run_mean_reversion), 20%
validation (grid search over k/z_stop_room/calib_window/tau_threshold,
selecting by NET-of-cost total PnL, not raw PnL), 20% test (ONE-SHOT
evaluation of the validation winner, no further tuning).

Cost model: XAUUSD, 1 pip = 0.1 price units (2-decimal quote). Round-trip
cost = 1.2 pip = 0.12 price units (Standard Account assumption), used both
as the friction-hurdle spread input and the cost subtracted per trade.

z_stop is parameterized as z_entry (k) + a small "room past entry" (see
kalman_mean_reversion.py's z_stop docstring) rather than an independent
absolute value, to match "Dynamic Stop Loss at Z_stop=0.8" read as
room-past-entry, not an absolute Z smaller than the entry threshold.

Usage:
    python scripts/research/kalman_walkforward.py --symbol XAUUSD
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pymysql
import pymysql.cursors
from dotenv import load_dotenv
import os

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from analysis.strategies.kalman_mean_reversion import run_mean_reversion  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics, deflated_sharpe_ratio, sharpe_ratio  # noqa: E402

DB = dict(
    host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "3308")),
    user=os.getenv("DB_USER", "quant_user"), password=os.getenv("DB_PASSWORD", ""),
    charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
)
RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd", "NDX100": "raw_ndx100"}
# NDX100 is an index CFD, not FX -- "pip" here just means 1 index point
# (its own natural price unit), not a fractional-pip forex convention.
PIP = {"XAUUSD": 0.1, "EURUSD": 0.0001, "NDX100": 1.0}
ROUND_TRIP_PIPS = 1.2  # Standard Account assumption
HMM_CALIB_BARS = 2000


def load(symbol, table):
    conn = pymysql.connect(**DB, database=RAW_DB[symbol])
    cur = conn.cursor()
    cur.execute(f"SELECT price_datetime, high_price, low_price, close_price FROM {table} ORDER BY price_datetime ASC")
    rows = cur.fetchall()
    conn.close()
    df = pd.DataFrame(rows)
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    for c in ("high_price", "low_price", "close_price"):
        df[c] = df[c].astype(float)
    return df


def split_60_20_20(df):
    n = len(df)
    i_train = int(n * 0.6)
    i_val = int(n * 0.8)
    return df.iloc[:i_train].reset_index(drop=True), df.iloc[i_train:i_val].reset_index(drop=True), df.iloc[i_val:].reset_index(drop=True)


def sim_pnl(res):
    pnl = []
    pos = 0
    entry = None
    for _, r in res.iterrows():
        if r["signal"] in ("long", "short"):
            pos = 1 if r["signal"] == "long" else -1
            entry = r["close"]
        elif r["signal"] is not None and entry is not None:
            pnl.append(pos * (r["close"] - entry))
            pos, entry = 0, None
    return np.array(pnl)


def run_cfg(dset, cost, **kw):
    res = run_mean_reversion(dset["price_datetime"], dset["close_price"], dset["high_price"], dset["low_price"], **kw)
    pnl = sim_pnl(res)
    net = pnl - cost
    return net


def profit_factor(net):
    wins = net[net > 0]
    losses = net[net < 0]
    return wins.sum() / abs(losses.sum()) if losses.sum() != 0 else (float("inf") if wins.sum() > 0 else 0.0)


def evaluate_timeframe(symbol, table):
    df = load(symbol, table)
    train, val, test = split_60_20_20(df)
    pip = PIP[symbol]
    cost = ROUND_TRIP_PIPS * pip
    days = {
        "train": (train["price_datetime"].max() - train["price_datetime"].min()).days,
        "val": (val["price_datetime"].max() - val["price_datetime"].min()).days,
        "test": (test["price_datetime"].max() - test["price_datetime"].min()).days,
    }
    print(f"=== {symbol} {table}: train={len(train)} ({days['train']}d) "
          f"val={len(val)} ({days['val']}d) test={len(test)} ({days['test']}d) ===")

    # calib_window swept densely (not just 3 arbitrary picks) -- the video's
    # own guidance is that this has no universal answer and must be walk-
    # forward optimized per asset/timeframe, same as everything else here.
    # (q_mult, obs_noise_scale) swept as paired combos (Q tied to realized
    # vol via q_mult, R tied to spread/market noise via obs_noise_scale,
    # per the spec's Q/R parameterization) rather than a full cross, to
    # keep the grid tractable. tau_threshold expressed as a FRACTION of
    # calib_window (half-life is bar-count-scaled, so a fixed absolute
    # bar count doesn't transfer across calib_window values) or None
    # (entry-side filter off). half_life_mult fixed at 2.0 (the spec's
    # literal "2*tau" time-stop rule, not something to search).
    # tau_frac widened -- 0.5 (half of calib_window) turned out to block
    # entries almost entirely (n collapsed to 3-9 trades, see RESULTS.md
    # experiment 9). 1.0/1.5/None give the entry-side filter much more
    # room, from "as slow as the calibration window itself" up to "off".
    grid = []
    for calib_window in (40, 60, 80, 120, 160, 200, 240, 320):
        for k in (1.8, 2.2):
            for q_mult, obs_noise_scale in ((1.0, 1.0), (2.0, 0.5), (1.0, 0.5), (2.0, 1.0)):
                for tau_frac in (1.0, 1.5, None):
                    grid.append(dict(
                        calib_window=calib_window, recalib_every=5,
                        obs_noise_scale=obs_noise_scale, q_mult=q_mult, k=k,
                        z_stop=k + 1.0, half_life_mult=2.0,
                        hmm_calib_bars=HMM_CALIB_BARS, hmm_block_states=(2,),
                        tau_threshold=(calib_window * tau_frac) if tau_frac else None,
                        spread=cost, friction_hurdle_mult=2.5,
                    ))

    # Minimum trade count on validation before a config is even eligible to
    # win the selection -- ranking by raw net PnL alone (previous version)
    # kept picking sparse configs (n=3-6) that got lucky on one or two big
    # trades, not configs with a real, repeatable edge. MIN_VAL_TRADES is a
    # floor, not a target -- still small in absolute terms, but enough that
    # one outlier trade can't single-handedly win the ranking.
    MIN_VAL_TRADES = 15
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
    print(f"  validation grid ({len(grid)} configs, {n_eligible} with n>={MIN_VAL_TRADES}) done in {time.time()-t0:.1f}s")
    print("  top 5 on VALIDATION (by net PnL, among configs with n>=%d trades):" % MIN_VAL_TRADES)
    for total, pf, n, kw, eligible in results[:5]:
        wk = n / days["val"] * 7 if days["val"] else 0
        tau_disp = f"{kw['tau_threshold']:.0f}" if kw["tau_threshold"] is not None else "None"
        print(f"    net={total:.2f} PF={pf:.2f} n={n} ({wk:.2f}/wk) eligible={eligible} "
              f"calib={kw['calib_window']} k={kw['k']} z_stop={kw['z_stop']:.1f} "
              f"q_mult={kw['q_mult']} obs_noise={kw['obs_noise_scale']} tau={tau_disp}")

    if not results[0][4]:
        print(f"  WARNING: no config reached {MIN_VAL_TRADES} trades on validation -- "
              f"falling back to the highest-n config instead of net PnL.")
        results.sort(reverse=True, key=lambda r: r[2])
    best_kw = results[0][3]
    net_test = run_cfg(test, cost, **best_kw)
    tm = trade_metrics(net_test)
    
    # Sharpe sample for the DSR deflation benchmark must be drawn from
    # ELIGIBLE (n>=MIN_VAL_TRADES) configs only -- results[:20] on its own
    # can include ineligible entries (net pinned to -1e18) whenever fewer
    # than 20 configs cleared the eligibility bar, which silently corrupts
    # sr_variance_across_trials (confirmed: EURUSD m5 had only 15 eligible
    # configs, and the 5 ineligible ones that leaked into the top-20 slice
    # collapsed DSR to ~0 despite a good-looking PF=2.83).
    
    eligible_results = [r for r in results if r[4]]
    sharpes = np.array([sharpe_ratio(run_cfg(val, cost, **r[3])) for r in eligible_results[:20] if len(run_cfg(val, cost, **r[3])) >= 2])
    sr_var = float(sharpes.var(ddof=1)) if len(sharpes) >= 2 else 0.0
    dsr = deflated_sharpe_ratio(net_test, n_trials=len(grid), sr_variance_across_trials=sr_var)

    wk_test = tm["n_trades"] / days["test"] * 7 if days["test"] and tm["n_trades"] else 0
    print(f"  >>> TEST (one-shot, best-from-validation): calib={best_kw['calib_window']} k={best_kw['k']} "
          f"z_stop={best_kw['z_stop']:.1f} q_mult={best_kw['q_mult']} obs_noise={best_kw['obs_noise_scale']} "
          f"tau={best_kw['tau_threshold']}")
    print(f"      n={tm['n_trades']} ({wk_test:.2f}/wk) win_rate={tm['win_rate']} "
          f"PF={tm['profit_factor']} expectancy={tm['expectancy_r']} maxDD={tm['max_drawdown_r']} "
          f"DSR={dsr['dsr']}")
    return {
        "symbol": symbol, "table": table, "best_config": best_kw,
        "test_n": tm["n_trades"], "test_weekly": wk_test, "test_win_rate": tm["win_rate"],
        "test_pf": tm["profit_factor"], "test_expectancy": tm["expectancy_r"],
        "test_maxdd": tm["max_drawdown_r"], "test_dsr": dsr["dsr"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--timeframes", default="m5,m15,h1", help="comma-separated subset of m5,m15,h1")
    args = parser.parse_args()

    tables = [t.strip() for t in args.timeframes.split(",")]
    summary = []
    for table in tables:
        summary.append(evaluate_timeframe(args.symbol, table))
        print()

    print("=" * 100)
    print(f"SUMMARY -- {args.symbol}, target PF>1.2, ~1-3+ trades/week, win_rate>55-60%, DSR>0.95")
    print("=" * 100)
    print(f"{'TF':<6}{'n(test)':<9}{'per/wk':<9}{'win%':<8}{'PF':<8}{'maxDD':<10}{'DSR':<8}")
    for s in summary:
        wr = f"{s['test_win_rate']*100:.1f}" if s["test_win_rate"] is not None else "-"
        pf = f"{s['test_pf']:.2f}" if s["test_pf"] is not None else "-"
        print(f"{s['table']:<6}{s['test_n']:<9}{s['test_weekly']:<9.2f}{wr:<8}{pf:<8}{s['test_maxdd']:<10.2f}{s['test_dsr']:<8.4f}")


if __name__ == "__main__":
    main()
