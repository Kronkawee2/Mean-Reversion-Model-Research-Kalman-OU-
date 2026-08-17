"""
Runs ConfluenceZoneEngine (analysis/strategies/confluence_zone_engine.py)
against h1 bars resampled to h4/h6/d1, for both modes, and upserts into
curated_<symbol>.confluence_zones.

Usage:
    python scripts/detection/run_confluence_zone_detection.py --symbol XAUUSD
    python scripts/detection/run_confluence_zone_detection.py --symbol XAUUSD --timeframe h4 --mode mode_a_2factor --no-write
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.confluence_zone_engine import (  # noqa: E402
    detect_confluence_zones, MODE_MIN_FACTORS,
)
from analysis.features.indicator_features import resample_ohlc  # noqa: E402
from analysis.rolling_window import rolling_window_start, ROLLING_WINDOW_DAYS  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
RESAMPLE_RULE = {"h4": "4h", "h6": "6h", "d1": "1d"}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_htf_bars(symbol: str, timeframe: str) -> pd.DataFrame:
    # Resample from h1, same as every other HTF consumer in this project.
    # h1 itself carries the full backfilled history, so pull only the
    # rolling-window slice needed here rather than the full 23 years.
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price_datetime, open_price, high_price, low_price, close_price "
                "FROM h1 WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df_h1 = pd.DataFrame(rows)
    df_h1["price_datetime"] = pd.to_datetime(df_h1["price_datetime"])
    return resample_ohlc(df_h1, rule=RESAMPLE_RULE[timeframe])


def upsert_zones(symbol: str, zones: pd.DataFrame) -> int:
    if zones.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO confluence_zones
        (symbol, timeframe, mode, direction, zone_core_top, zone_core_bottom,
         zone_full_top, zone_full_bottom, factor_count, confidence_score, factors,
         created_at_bar, last_factor_at_bar, status, resolved_at_bar)
    VALUES
        (%(symbol)s, %(timeframe)s, %(mode)s, %(direction)s, %(zone_core_top)s, %(zone_core_bottom)s,
         %(zone_full_top)s, %(zone_full_bottom)s, %(factor_count)s, %(confidence_score)s, %(factors)s,
         %(created_at_bar)s, %(last_factor_at_bar)s, %(status)s, %(resolved_at_bar)s)
    ON DUPLICATE KEY UPDATE
        zone_core_top = VALUES(zone_core_top), zone_core_bottom = VALUES(zone_core_bottom),
        zone_full_top = VALUES(zone_full_top), zone_full_bottom = VALUES(zone_full_bottom),
        factor_count = VALUES(factor_count), confidence_score = VALUES(confidence_score),
        factors = VALUES(factors), last_factor_at_bar = VALUES(last_factor_at_bar),
        status = VALUES(status), resolved_at_bar = VALUES(resolved_at_bar)
    """
    rows = zones.to_dict("records")
    for row in rows:
        row["factors"] = json.dumps(row["factors"], default=str)
        if pd.isna(row.get("resolved_at_bar")):
            row["resolved_at_bar"] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(symbol: str, timeframe: str, mode: str, zones: pd.DataFrame, n_days: float):
    print(f"\n[{symbol} {timeframe} {mode}] zones: {len(zones)} over {n_days:.0f} days "
          f"= {len(zones) / n_days:.2f}/day")
    if zones.empty:
        return
    print(zones["direction"].value_counts().to_string())
    print(zones["factor_count"].value_counts().sort_index().to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--timeframe", default="all", choices=list(RESAMPLE_RULE) + ["all"])
    parser.add_argument("--mode", default="both", choices=list(MODE_MIN_FACTORS) + ["both"])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    timeframes = list(RESAMPLE_RULE) if args.timeframe == "all" else [args.timeframe]
    modes = list(MODE_MIN_FACTORS) if args.mode == "both" else [args.mode]

    print(f"Rolling window: {ROLLING_WINDOW_DAYS} days, start={rolling_window_start()}")

    for timeframe in timeframes:
        bars = load_htf_bars(symbol, timeframe)
        n_days = (bars["price_datetime"].max() - bars["price_datetime"].min()).total_seconds() / 86400
        print(f"\n{symbol} {timeframe}: {len(bars)} bars, {n_days:.0f} days "
              f"({bars['price_datetime'].min()} -> {bars['price_datetime'].max()})")

        for mode in modes:
            zones = detect_confluence_zones(bars, symbol=symbol, timeframe=timeframe, mode=mode)
            print_report(symbol, timeframe, mode, zones, n_days)
            if not args.no_write:
                n = upsert_zones(symbol, zones)
                print(f"[{symbol} {timeframe} {mode}] Upserted {n} zones")


if __name__ == "__main__":
    main()
