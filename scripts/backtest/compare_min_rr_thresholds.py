"""
Exploratory comparison of minimum structural_rr thresholds, layered on top
of the production stop-cap fix (MAX_STOP_ATR_MULTIPLE=1.5, see
structural_tp_engine.py and docs/DECISIONS.md). That fix corrected the
stop/target mechanics but didn't resolve the backtest's "win often, lose
big" fragility -- this tests a different lever: instead of reshaping every
trigger's R:R after the fact, reject triggers whose structural R:R is
already below a cutoff, on the theory that low-R:R signals (not stop
mechanics) are what's dragging the aggregate profile down.

Variants recomputed IN-MEMORY from the same raw triggers/zones/entry/ATR
data as compare_structural_tp_variants.py and NOT written back to
ltf_trigger_signals or backtest_runs/backtest_trades -- exploratory only,
same non-production status as that script. No threshold is picked as a
winner here; this reports the comparison table for a human decision.

MULTIPLE-COMPARISONS CAVEAT (same as compare_structural_tp_variants.py):
testing several thresholds against the same single-regime history is
itself a form of multiple comparisons the DSR values below do not correct
for across thresholds (only the Mode A vs Mode B selection within a given
threshold, N=2).

Usage:
    python scripts/backtest/compare_min_rr_thresholds.py --symbol XAUUSD --mode both
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.structural_tp_engine import compute_structural_targets  # noqa: E402
from analysis.strategies.ltf_trigger_engine import MODES  # noqa: E402
from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402
from analysis.backtester.deflated_sharpe import deflated_sharpe_ratio, trade_metrics, sharpe_ratio  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}

MIN_RR_THRESHOLDS = [None, 1.0, 1.5, 2.0, 3.0]  # None = no filter, current production behavior
MIN_TRADES_PER_12_MONTHS = 200


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_all_triggers(symbol, ltf_timeframe, mode):
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, symbol, ltf_timeframe, mode, direction, confirmed_at_bar, "
                "htf_zone_type, htf_zone_top, htf_zone_bottom "
                "FROM ltf_trigger_signals WHERE symbol=%s AND ltf_timeframe=%s AND mode=%s "
                "AND confirmed_at_bar >= %s",
                (symbol, ltf_timeframe, mode, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_htf_zones(symbol):
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar "
                "FROM smc_signals WHERE symbol=%s AND timeframe='h1' AND created_at_bar >= %s",
                (symbol, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_raw_bars(symbol, timeframe):
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, high_price, low_price FROM `{timeframe}` "
                "WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    for c in ("high_price", "low_price"):
        df[c] = df[c].astype(float)
    return df


def load_h1_atr(symbol):
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_datetime, atr_14 FROM features WHERE symbol=%s AND timeframe='h1' AND bar_datetime >= %s",
                (symbol, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {r["bar_datetime"]: float(r["atr_14"]) for r in rows}


def load_entry_prices(symbol, ltf_timeframe, distinct_bars):
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, close_price FROM `{ltf_timeframe}` "
                f"WHERE price_datetime IN ({','.join(['%s'] * len(distinct_bars))})",
                tuple(distinct_bars.tolist()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {r["price_datetime"]: float(r["close_price"]) for r in rows}


def run_threshold(min_rr, triggers_base, zones, m15_bars, m5_bars, entry_by_bar, atr_by_h1_bar, cutoff):
    triggers = triggers_base.copy()
    triggers["entry_price"] = triggers["confirmed_at_bar"].map(entry_by_bar)
    triggers["atr_14"] = triggers["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)

    # Production defaults -- stop_mode='zone_far_edge' with the MAX_STOP_ATR_MULTIPLE
    # cap already baked in, same as run_structural_tp.py's live behavior.
    targets = compute_structural_targets(triggers, zones)
    targets["id"] = triggers["id"].values

    structural = targets[targets["target_status"] == "structural"].copy()
    n_before_rr_filter = len(structural)
    if min_rr is not None:
        structural = structural[structural["structural_rr"].astype(float) >= min_rr]
    n_structural = len(structural)

    if structural.empty:
        return None

    trades, skipped = simulate(structural, m15_bars, m5_bars)
    full_decided = trades[trades["exit_reason"].isin(["win", "loss"])]
    test_trades = trades[trades["entry_bar_datetime"] >= cutoff]
    test_decided = test_trades[test_trades["exit_reason"].isin(["win", "loss"])]

    return {
        "n_before_rr_filter": n_before_rr_filter, "n_structural": n_structural,
        "full_trades": trades, "full_decided": full_decided,
        "test_trades": test_trades, "test_decided": test_decided,
    }


def summarize(decided_r, n_trials, sr_variance):
    r = decided_r["r_outcome"].astype(float).values if len(decided_r) else np.array([])
    tm = trade_metrics(r)
    dsr = deflated_sharpe_ratio(r, n_trials=n_trials, sr_variance_across_trials=sr_variance or 0.0)
    return tm, dsr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--ltf-timeframe", default="m15", choices=["m5", "m15"])
    parser.add_argument("--mode", default="both", choices=list(MODES) + ["both"])
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} data (raw bars, h1 zones, ATR, triggers)...")
    m15_bars = load_raw_bars(symbol, args.ltf_timeframe)
    m5_bars = load_raw_bars(symbol, "m5") if args.ltf_timeframe != "m5" else m15_bars
    zones = load_htf_zones(symbol)
    atr_by_h1_bar = load_h1_atr(symbol)
    start = m15_bars["price_datetime"].min()
    end = m15_bars["price_datetime"].max()
    cutoff = start + (end - start) * 0.7
    full_duration_days = (end - start).total_seconds() / 86400.0
    test_duration_days = (end - cutoff).total_seconds() / 86400.0
    full_floor = int(round(MIN_TRADES_PER_12_MONTHS * full_duration_days / 365.25))
    test_floor = int(round(MIN_TRADES_PER_12_MONTHS * test_duration_days / 365.25))
    print(f"Period: {start} -> {end}  |  OOS cutoff: {cutoff}")
    print(f"min_sample_floor_required: full={full_floor} ({full_duration_days:.0f}d)  test={test_floor} ({test_duration_days:.0f}d)")

    modes = list(MODES) if args.mode == "both" else [args.mode]

    all_results = {}  # (mode, threshold) -> result dict
    for mode in modes:
        triggers_base = load_all_triggers(symbol, args.ltf_timeframe, mode)
        if triggers_base.empty:
            print(f"[{mode}] No triggers found, skipping.")
            continue
        triggers_base["confirmed_at_bar"] = pd.to_datetime(triggers_base["confirmed_at_bar"])
        distinct_bars = pd.Series(triggers_base["confirmed_at_bar"].unique())
        entry_by_bar = load_entry_prices(symbol, args.ltf_timeframe, distinct_bars)

        for min_rr in MIN_RR_THRESHOLDS:
            label = "no_filter" if min_rr is None else f"rr>={min_rr}"
            print(f"Running {mode} / {label}...")
            result = run_threshold(min_rr, triggers_base, zones, m15_bars, m5_bars,
                                    entry_by_bar, atr_by_h1_bar, cutoff)
            all_results[(mode, label)] = result

    full_sharpe = {}
    for (mode, label), result in all_results.items():
        if result is None:
            continue
        r = result["full_decided"]["r_outcome"].astype(float).values
        full_sharpe[(mode, label)] = sharpe_ratio(r) if len(r) >= 2 else None

    rows = []
    for (mode, label), result in all_results.items():
        if result is None:
            print(f"[{mode}/{label}] No structural triggers survived this threshold — skipped.")
            continue
        other_modes = [m for m in modes if m != mode]
        other_sharpe = full_sharpe.get((other_modes[0], label)) if other_modes else None
        n_trials = 2 if other_sharpe is not None else 1

        full_tm, full_dsr = summarize(
            result["full_decided"], n_trials,
            float(np.var([full_sharpe[(mode, label)], other_sharpe], ddof=1))
            if other_sharpe is not None and full_sharpe.get((mode, label)) is not None else None,
        )
        test_tm, test_dsr = summarize(
            result["test_decided"], n_trials,
            float(np.var([full_sharpe[(mode, label)], other_sharpe], ddof=1))
            if other_sharpe is not None and full_sharpe.get((mode, label)) is not None else None,
        )

        for period_name, tm, dsr, decided, taken, floor in (
            ("full", full_tm, full_dsr, result["full_decided"], len(result["full_trades"]), full_floor),
            ("test", test_tm, test_dsr, result["test_decided"], len(result["test_trades"]), test_floor),
        ):
            rows.append({
                "mode": mode, "threshold": label, "period": period_name,
                "n_before_rr_filter": result["n_before_rr_filter"], "n_structural": result["n_structural"],
                "trades_taken": taken, "n_decided": len(decided),
                "floor_required": floor, "meets_floor": len(decided) >= floor,
                "win_rate": tm["win_rate"], "profit_factor": tm["profit_factor"],
                "expectancy_r": tm["expectancy_r"], "max_drawdown_r": tm["max_drawdown_r"],
                "sharpe": dsr["sharpe"], "dsr": dsr["dsr"],
            })

    report = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}" if isinstance(x, float) else str(x))
    for mode in modes:
        print(f"\n{'='*110}\n{symbol} / {mode}\n{'='*110}")
        sub = report[report["mode"] == mode].drop(columns=["mode"])
        print(sub.to_string(index=False))

    below_floor = report[~report["meets_floor"]]
    if not below_floor.empty:
        print("\n" + "=" * 110)
        print("BELOW STATISTICAL FLOOR -- metrics for these rows are not reliable regardless of how good they look:")
        print(below_floor[["threshold", "period", "n_decided", "floor_required"]].to_string(index=False))
        print("=" * 110)

    print("\n" + "=" * 110)
    print("MULTIPLE-COMPARISONS CAVEAT: several thresholds were tested against the same single-regime")
    print("history. The DSR values above correct only for the Mode A vs Mode B selection WITHIN each")
    print("threshold (N=2) -- they do NOT correct for having tried multiple thresholds side by side here.")
    print("No threshold is being recommended.")
    print("=" * 110)


if __name__ == "__main__":
    main()
