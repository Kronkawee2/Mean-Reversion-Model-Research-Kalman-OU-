"""
Runs LTFTriggerEngine against real synced LTF (m5/m15) data and the
already-persisted h1 SMC zones, upserting confirmed triggers into
curated_<symbol>.ltf_trigger_signals. Prints a summary + concrete examples
for manual/chart cross-checking, same pattern as the other run_*.py
detection scripts.

Pass 2 of strategies/ -- LTF trigger confirmation only. See
analysis/strategies/ltf_trigger_engine.py module docstring for the full
design (two selectable confirmation modes, confirmation window, why m15 is
the default LTF timeframe) and the three decisions confirmed with the user
before building.

Usage:
    python scripts/detection/run_ltf_trigger_detection.py --symbol XAUUSD --mode choch_only
    python scripts/detection/run_ltf_trigger_detection.py --symbol XAUUSD --mode choch_sweep
    python scripts/detection/run_ltf_trigger_detection.py --symbol XAUUSD --mode both --ltf-timeframe m5 --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.ltf_trigger_engine import LTFTriggerEngine, MODES  # noqa: E402
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


def load_ltf_bars(symbol: str, ltf_timeframe: str) -> pd.DataFrame:
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, high_price, low_price, close_price FROM `{ltf_timeframe}` "
                f"WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
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


def upsert_triggers(symbol: str, triggers: pd.DataFrame) -> int:
    if triggers.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO ltf_trigger_signals
        (symbol, ltf_timeframe, mode, direction, htf_zone_type, htf_zone_top, htf_zone_bottom,
         htf_zone_created_at_bar, touch_bar_datetime, choch_bar_datetime, sweep_bar_datetime,
         sweep_type, confirmed_at_bar)
    VALUES
        (%(symbol)s, %(ltf_timeframe)s, %(mode)s, %(direction)s, %(htf_zone_type)s, %(htf_zone_top)s,
         %(htf_zone_bottom)s, %(htf_zone_created_at_bar)s, %(touch_bar_datetime)s, %(choch_bar_datetime)s,
         %(sweep_bar_datetime)s, %(sweep_type)s, %(confirmed_at_bar)s)
    ON DUPLICATE KEY UPDATE
        direction = VALUES(direction), sweep_bar_datetime = VALUES(sweep_bar_datetime),
        sweep_type = VALUES(sweep_type), confirmed_at_bar = VALUES(confirmed_at_bar)
    """
    rows = triggers.to_dict("records")
    for row in rows:
        if pd.isna(row.get("sweep_bar_datetime")):
            row["sweep_bar_datetime"] = None
        if pd.isna(row.get("sweep_type")) or row.get("sweep_type") is None:
            row["sweep_type"] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(mode: str, triggers: pd.DataFrame, n_examples: int = 3):
    print(f"\n[{mode}] Total triggers: {len(triggers)}")
    if triggers.empty:
        return
    print(triggers["direction"].value_counts().to_string())
    print(f"\n[{mode}] Last {n_examples} triggers:")
    for _, row in triggers.tail(n_examples).iterrows():
        sweep_note = f"  sweep={row['sweep_bar_datetime']}({row['sweep_type']})" if pd.notnull(row["sweep_bar_datetime"]) else ""
        print(
            f"  confirmed={row['confirmed_at_bar']}  {row['direction']:8s}  zone={row['htf_zone_type']} "
            f"[{row['htf_zone_bottom']:.2f}-{row['htf_zone_top']:.2f}]  touch={row['touch_bar_datetime']}  "
            f"choch={row['choch_bar_datetime']}{sweep_note}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--ltf-timeframe", default="m15", choices=["m5", "m15"])
    parser.add_argument("--mode", default="both", choices=list(MODES) + ["both"])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} {args.ltf_timeframe} bars + h1 SMC zones from `{SILVER_DB[symbol]}`...")
    ltf_bars = load_ltf_bars(symbol, args.ltf_timeframe)
    if ltf_bars.empty:
        print(f"No {args.ltf_timeframe} data available for {symbol} — nothing to do.")
        return
    htf_zones = load_htf_zones(symbol)
    print(f"Loaded {len(ltf_bars)} {args.ltf_timeframe} bars: "
          f"{ltf_bars['price_datetime'].min()} -> {ltf_bars['price_datetime'].max()}")
    print(f"Loaded {len(htf_zones)} h1 SMC zones")

    modes = list(MODES) if args.mode == "both" else [args.mode]
    engine = LTFTriggerEngine()

    for mode in modes:
        triggers = engine.compute_triggers(
            ltf_bars, htf_zones, symbol=symbol, ltf_timeframe=args.ltf_timeframe, mode=mode,
        )
        print_report(mode, triggers)
        if not args.no_write:
            n = upsert_triggers(symbol, triggers)
            print(f"[{mode}] Upserted {n} trigger rows into `{SILVER_DB[symbol]}`.ltf_trigger_signals")


if __name__ == "__main__":
    main()
