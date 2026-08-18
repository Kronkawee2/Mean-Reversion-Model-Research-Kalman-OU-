"""
Runs SMCZoneStateEngine against real synced OHLCV data and upserts the
resulting zones into curated_<symbol>.smc_signals. Also prints a summary
report (counts per state, example zones) for manual sanity-checking.

Usage:
    python scripts/detection/run_smc_zone_detection.py --symbol XAUUSD --timeframe h1
    python scripts/detection/run_smc_zone_detection.py --symbol EURUSD --timeframe d1 --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.smc_crt.zone_state import SMCZoneStateEngine  # noqa: E402
from analysis.features.indicator_features import resample_ohlc  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "gold_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
RESAMPLE_RULE = {"h4": "4h", "h6": "6h", "d1": "1d"}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_ohlcv(symbol: str, timeframe: str) -> pd.DataFrame:
    """h1 loads straight from raw_<symbol>.h1. h4/h6/d1 resample from that
    same h1 table instead of reading raw_<symbol>.{h4,h6,d1} directly --
    those raw tables are Yahoo-sourced and DST-misaligned (h6 isn't synced
    at all), the same reason the dashboard chart and the Confluence Zone
    Engine's detection script both resample from h1 rather than read them
    (see docs/DECISIONS.md).

    Filtered to the rolling window before detection runs, not after --
    h1 now goes back 23 years (see the H1 backfill entry in
    docs/DECISIONS.md) and running SMCZoneStateEngine's full O(n^2)-ish
    swing/OB/FVG scan over that whole depth is what made the earlier
    full-history attempt hang; every consumer of smc_signals only ever
    reads the rolling 2-year window anyway, so there's no detection-side
    reason to compute further back than that."""
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price_datetime, open_price, high_price, low_price, close_price FROM h1 "
                "WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if timeframe == "h1" or df.empty:
        return df
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    return resample_ohlc(df, rule=RESAMPLE_RULE[timeframe])


def upsert_zones(symbol: str, zones: pd.DataFrame) -> int:
    if zones.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO smc_signals
        (symbol, timeframe, zone_type, zone_top, zone_bottom, state,
         created_at_bar, mitigated_at_bar, invalidated_at_bar)
    VALUES
        (%(symbol)s, %(timeframe)s, %(zone_type)s, %(zone_top)s, %(zone_bottom)s, %(state)s,
         %(created_at_bar)s, %(mitigated_at_bar)s, %(invalidated_at_bar)s)
    ON DUPLICATE KEY UPDATE
        zone_top = VALUES(zone_top),
        zone_bottom = VALUES(zone_bottom),
        state = VALUES(state),
        mitigated_at_bar = VALUES(mitigated_at_bar),
        invalidated_at_bar = VALUES(invalidated_at_bar)
    """
    rows = zones.to_dict("records")
    for row in rows:
        for key in ("mitigated_at_bar", "invalidated_at_bar"):
            if pd.isna(row[key]):
                row[key] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(zones: pd.DataFrame):
    print(f"\nTotal zones detected: {len(zones)}")
    if zones.empty:
        return
    print("\nBy state:")
    print(zones["state"].value_counts().to_string())
    print("\nBy zone_type:")
    print(zones["zone_type"].value_counts().to_string())

    print("\nExample zones (up to 3 per type):")
    for zt, group in zones.groupby("zone_type"):
        for _, row in group.head(3).iterrows():
            print(
                f"  [{zt}] {row['created_at_bar']}  "
                f"top={row['zone_top']:.5f} bottom={row['zone_bottom']:.5f}  "
                f"state={row['state']}"
                + (f" mitigated_at={row['mitigated_at_bar']}" if pd.notnull(row['mitigated_at_bar']) else "")
                + (f" invalidated_at={row['invalidated_at_bar']}" if pd.notnull(row['invalidated_at_bar']) else "")
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--timeframe", default="h1", choices=["h1", "h4", "h6", "d1"])
    parser.add_argument("--no-write", action="store_true", help="detect and report only, skip DB upsert")
    args = parser.parse_args()

    print(f"Loading {args.symbol} {args.timeframe} from `{RAW_DB[args.symbol]}`...")
    df = load_ohlcv(args.symbol, args.timeframe)
    print(f"Loaded {len(df)} bars: {df['price_datetime'].min()} -> {df['price_datetime'].max()}")

    engine = SMCZoneStateEngine()
    zones = engine.detect_zones(df, symbol=args.symbol, timeframe=args.timeframe)

    print_report(zones)

    if not args.no_write:
        n = upsert_zones(args.symbol, zones)
        print(f"\nUpserted {n} zones into `{SILVER_DB[args.symbol]}`.smc_signals")


if __name__ == "__main__":
    main()
