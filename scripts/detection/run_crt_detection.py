"""
Runs CRTStateEngine against real synced OHLCV data and upserts the
resulting signals into curated_<symbol>.crt_signals. Also prints a summary
report for manual sanity-checking, same pattern as run_smc_zone_detection.py.

Asian range + sweep detection always reads h1 (session boundaries are
UTC-clock-defined and need h1 granularity). Equilibrium reads whatever
--timeframe is passed (h4/h6/d1).

Usage:
    python scripts/detection/run_crt_detection.py --symbol XAUUSD --timeframe h4
    python scripts/detection/run_crt_detection.py --symbol EURUSD --timeframe d1 --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.smc_crt.crt_state import CRTStateEngine  # noqa: E402

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


def load_ohlcv(symbol: str, timeframe: str) -> pd.DataFrame:
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, open_price, high_price, low_price, close_price "
                f"FROM `{timeframe}` ORDER BY price_datetime ASC"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def upsert_signals(symbol: str, signals: pd.DataFrame) -> int:
    if signals.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO crt_signals
        (symbol, timeframe, signal_type, session_date, bar_datetime,
         level_price, range_high, range_low, equilibrium_price, zone_bias,
         state, sweep_direction, swept_at_bar, expired_at_bar)
    VALUES
        (%(symbol)s, %(timeframe)s, %(signal_type)s, %(session_date)s, %(bar_datetime)s,
         %(level_price)s, %(range_high)s, %(range_low)s, %(equilibrium_price)s, %(zone_bias)s,
         %(state)s, %(sweep_direction)s, %(swept_at_bar)s, %(expired_at_bar)s)
    ON DUPLICATE KEY UPDATE
        level_price = VALUES(level_price),
        range_high = VALUES(range_high),
        range_low = VALUES(range_low),
        equilibrium_price = VALUES(equilibrium_price),
        zone_bias = VALUES(zone_bias),
        state = VALUES(state),
        sweep_direction = VALUES(sweep_direction),
        swept_at_bar = VALUES(swept_at_bar),
        expired_at_bar = VALUES(expired_at_bar)
    """
    rows = signals.to_dict("records")
    nullable = (
        "session_date", "level_price", "range_high", "range_low", "equilibrium_price",
        "zone_bias", "state", "sweep_direction", "swept_at_bar", "expired_at_bar",
    )
    for row in rows:
        for key in nullable:
            if pd.isna(row.get(key)):
                row[key] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_asian_report(signals: pd.DataFrame, n_days: int = 5):
    print(f"\nTotal Asian range/sweep signals: {len(signals)}")
    if signals.empty:
        return
    print("\nBy state:")
    print(signals["state"].value_counts().to_string())

    highs = signals[signals["signal_type"] == "asian_range_high"].sort_values("session_date")
    lows = signals[signals["signal_type"] == "asian_range_low"].sort_values("session_date")
    print(f"\nFirst {n_days} sessions (Asian high/low + state):")
    for d in list(highs["session_date"].unique())[:n_days]:
        h = highs[highs["session_date"] == d].iloc[0]
        l = lows[lows["session_date"] == d].iloc[0]
        print(
            f"  {d}: high={h['level_price']:.5f} ({h['state']}"
            + (f", swept_at={h['swept_at_bar']}" if pd.notnull(h['swept_at_bar']) else "") + ")  "
            f"low={l['level_price']:.5f} ({l['state']}"
            + (f", swept_at={l['swept_at_bar']}" if pd.notnull(l['swept_at_bar']) else "") + ")"
        )

    n_swept = (signals["state"] == "swept").sum()
    print(f"\nTotal sweeps detected: {n_swept} out of {len(signals)} range-levels "
          f"over {signals['session_date'].nunique()} sessions")


def print_equilibrium_report(signals: pd.DataFrame, n: int = 5):
    print(f"\nTotal equilibrium signals: {len(signals)}")
    if signals.empty:
        return
    print(f"\nFirst {n} candles:")
    for _, row in signals.head(n).iterrows():
        print(
            f"  {row['bar_datetime']}  high={row['range_high']:.5f} low={row['range_low']:.5f} "
            f"eq={row['equilibrium_price']:.5f}  bias={row['zone_bias']}"
        )
    print("\nBias distribution:")
    print(signals["zone_bias"].value_counts().to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--timeframe", default="h4", choices=["h4", "h6", "d1"],
                         help="timeframe for Range Equilibrium; Asian range/sweep always uses h1")
    parser.add_argument("--no-write", action="store_true", help="detect and report only, skip DB upsert")
    args = parser.parse_args()

    engine = CRTStateEngine()

    print(f"Loading {args.symbol} h1 from `{RAW_DB[args.symbol]}` for Asian range/sweep...")
    df_h1 = load_ohlcv(args.symbol, "h1")
    if df_h1.empty:
        print(f"No h1 data available for {args.symbol} — skipping Asian range/sweep detection.")
        asian_signals = pd.DataFrame()
    else:
        print(f"Loaded {len(df_h1)} h1 bars: {df_h1['price_datetime'].min()} -> {df_h1['price_datetime'].max()}")
        asian_signals = engine.detect_asian_sweeps(df_h1, symbol=args.symbol, timeframe="h1")
        print_asian_report(asian_signals)

    print(f"\nLoading {args.symbol} {args.timeframe} from `{RAW_DB[args.symbol]}` for Range Equilibrium...")
    df_htf = load_ohlcv(args.symbol, args.timeframe)
    print(f"Loaded {len(df_htf)} {args.timeframe} bars: {df_htf['price_datetime'].min()} -> {df_htf['price_datetime'].max()}")
    eq_signals = engine.calc_equilibrium(df_htf, symbol=args.symbol, timeframe=args.timeframe)
    print_equilibrium_report(eq_signals)

    if not args.no_write:
        n1 = upsert_signals(args.symbol, asian_signals)
        n2 = upsert_signals(args.symbol, eq_signals)
        print(f"\nUpserted {n1} Asian range/sweep signals and {n2} equilibrium signals "
              f"into `{SILVER_DB[args.symbol]}`.crt_signals")


if __name__ == "__main__":
    main()
