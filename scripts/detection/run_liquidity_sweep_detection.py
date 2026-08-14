"""
Runs LiquiditySweepStateEngine against real synced h1 data and upserts one
row per detected sweep event into curated_<symbol>.liquidity_sweeps. Prints
a summary + concrete examples for manual/chart cross-checking, same pattern
as run_crt_detection.py / run_smc_zone_detection.py.

Usage:
    python scripts/detection/run_liquidity_sweep_detection.py --symbol XAUUSD
    python scripts/detection/run_liquidity_sweep_detection.py --symbol EURUSD --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.smc_crt import LiquiditySweepStateEngine  # noqa: E402

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


def load_h1_bars(symbol: str) -> pd.DataFrame:
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price_datetime, high_price, low_price, close_price FROM h1 ORDER BY price_datetime ASC"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def upsert_sweeps(symbol: str, sweep_rows: pd.DataFrame) -> int:
    if sweep_rows.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO liquidity_sweeps
        (symbol, timeframe, sweep_type, direction, swept_level_price, bar_datetime)
    VALUES
        (%(symbol)s, %(timeframe)s, %(sweep_type)s, %(direction)s, %(swept_level_price)s, %(bar_datetime)s)
    ON DUPLICATE KEY UPDATE
        direction = VALUES(direction), swept_level_price = VALUES(swept_level_price)
    """
    rows = sweep_rows.to_dict("records")
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(sweep_rows: pd.DataFrame, n_examples: int = 5):
    print(f"\nTotal sweep events: {len(sweep_rows)}")
    if sweep_rows.empty:
        return
    print(sweep_rows["sweep_type"].value_counts().to_string())
    print(f"\nLast {n_examples} sweeps:")
    for _, row in sweep_rows.tail(n_examples).iterrows():
        print(
            f"  {row['bar_datetime']}  {row['sweep_type']:3s}  direction={row['direction']:8s}  "
            f"swept_level={row['swept_level_price']:.2f}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} h1 bars from `{RAW_DB[symbol]}`...")
    h1_bars = load_h1_bars(symbol)
    if h1_bars.empty:
        print(f"No h1 data available for {symbol} — nothing to do.")
        return
    print(f"Loaded {len(h1_bars)} h1 bars: {h1_bars['price_datetime'].min()} -> {h1_bars['price_datetime'].max()}")

    engine = LiquiditySweepStateEngine()
    sweep_rows = engine.detect_sweeps(h1_bars, symbol=symbol, timeframe="h1")

    print_report(sweep_rows)

    if not args.no_write:
        n = upsert_sweeps(symbol, sweep_rows)
        print(f"\nUpserted {n} sweep rows into `{SILVER_DB[symbol]}`.liquidity_sweeps")


if __name__ == "__main__":
    main()
