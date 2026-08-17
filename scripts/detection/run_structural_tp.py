"""
Runs StructuralTPEngine against already-persisted curated_<symbol>.
ltf_trigger_signals rows (both modes) plus h1 SMC zones, and UPDATEs each
row in place with entry_price/stop_price/opposing_zone_*/target_price/
structural_rr/target_status. Prints the R:R distribution (not just the
mean -- the spread is what shows whether this is behaving sensibly) plus
concrete examples across the range.

See analysis/strategies/structural_tp_engine.py module docstring for the
full design (Option 2 confirmed with the user, the 0.85 fraction, the
skip-not-default fallback, and the causal opposing-zone lookup).

This is a MECHANISM check, not a backtest: a sensible-looking R:R
distribution shows the engine's math is behaving (causal, no absurd
outliers, believable spread), not that structural TP produces good trading
outcomes. That question belongs to the backtester.

Usage:
    python scripts/detection/run_structural_tp.py --symbol XAUUSD --mode both
    python scripts/detection/run_structural_tp.py --symbol XAUUSD --mode choch_only --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.structural_tp_engine import (  # noqa: E402
    compute_structural_targets, STRUCTURAL_TP_FRACTION, MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE,
)
from analysis.strategies.ltf_trigger_engine import MODES  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_triggers(symbol: str, ltf_timeframe: str, mode: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, direction, htf_zone_top, htf_zone_bottom, confirmed_at_bar "
                "FROM ltf_trigger_signals WHERE symbol=%s AND ltf_timeframe=%s AND mode=%s "
                "AND confirmed_at_bar >= %s",
                (symbol, ltf_timeframe, mode, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_htf_zones(symbol: str) -> pd.DataFrame:
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


def load_h1_atr(symbol: str) -> pd.Series:
    """h1 ATR-14, indexed by bar_datetime -- for the minimum stop-distance floor."""
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


def load_entry_prices(symbol: str, ltf_timeframe: str, confirmed_at_bars: pd.Series) -> pd.Series:
    """LTF close price at each distinct confirmed_at_bar timestamp."""
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, close_price FROM `{ltf_timeframe}` "
                f"WHERE price_datetime IN ({','.join(['%s'] * len(confirmed_at_bars))})",
                tuple(confirmed_at_bars.tolist()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    price_by_dt = {r["price_datetime"]: float(r["close_price"]) for r in rows}
    return confirmed_at_bars.map(price_by_dt)


def update_targets(symbol: str, targets: pd.DataFrame) -> int:
    conn = _conn(SILVER_DB[symbol])
    sql = """
    UPDATE ltf_trigger_signals SET
        entry_price = %(entry_price)s, stop_price = %(stop_price)s,
        opposing_zone_type = %(opposing_zone_type)s, opposing_zone_top = %(opposing_zone_top)s,
        opposing_zone_bottom = %(opposing_zone_bottom)s, target_price = %(target_price)s,
        structural_rr = %(structural_rr)s, target_status = %(target_status)s
    WHERE id = %(id)s
    """
    # Select only the SQL's own columns -- targets carries extra input
    # columns (e.g. atr_14) that pymysql's dict-based executemany would
    # otherwise still try to escape (including any NaN in them, which
    # MySQL's connector rejects), even though they're never referenced
    # in the query string itself.
    update_cols = ["id", "entry_price", "stop_price", "opposing_zone_type", "opposing_zone_top",
                   "opposing_zone_bottom", "target_price", "structural_rr", "target_status"]
    rows = targets[update_cols].to_dict("records")
    for row in rows:
        for key in ("opposing_zone_type", "opposing_zone_top", "opposing_zone_bottom",
                    "target_price", "structural_rr"):
            if pd.isna(row.get(key)):
                row[key] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(mode: str, targets: pd.DataFrame):
    print(f"\n[{mode}] Total triggers: {len(targets)}")
    print(targets["target_status"].value_counts().to_string())

    structural = targets[targets["target_status"] == "structural"]
    if structural.empty:
        return
    rr = structural["structural_rr"].astype(float)
    print(f"\n[{mode}] structural_rr distribution (n={len(rr)}):")
    print(rr.describe(percentiles=[.05, .1, .25, .5, .75, .9, .95]).to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--ltf-timeframe", default="m15", choices=["m5", "m15"])
    parser.add_argument("--mode", default="both", choices=list(MODES) + ["both"])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    print(f"STRUCTURAL_TP_FRACTION = {STRUCTURAL_TP_FRACTION}, MIN_RISK_ATR_MULTIPLE = {MIN_RISK_ATR_MULTIPLE}, "
          f"MAX_STOP_ATR_MULTIPLE = {MAX_STOP_ATR_MULTIPLE}")
    htf_zones = load_htf_zones(symbol)
    print(f"Loaded {len(htf_zones)} h1 SMC zones for {symbol}")
    atr_by_h1_bar = load_h1_atr(symbol)
    print(f"Loaded {len(atr_by_h1_bar)} h1 ATR-14 values for {symbol}")

    modes = list(MODES) if args.mode == "both" else [args.mode]
    for mode in modes:
        triggers = load_triggers(symbol, args.ltf_timeframe, mode)
        if triggers.empty:
            print(f"[{mode}] No triggers found — nothing to do.")
            continue
        triggers["confirmed_at_bar"] = pd.to_datetime(triggers["confirmed_at_bar"])
        distinct_bars = pd.Series(triggers["confirmed_at_bar"].unique())
        entry_by_bar = dict(zip(distinct_bars, load_entry_prices(symbol, args.ltf_timeframe, distinct_bars)))
        triggers["entry_price"] = triggers["confirmed_at_bar"].map(entry_by_bar)
        triggers["atr_14"] = triggers["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)

        targets = compute_structural_targets(triggers, htf_zones)
        targets["id"] = triggers["id"].values
        print_report(mode, targets)

        if not args.no_write:
            n = update_targets(symbol, targets)
            print(f"[{mode}] Updated {n} trigger rows with structural TP data")


if __name__ == "__main__":
    main()
