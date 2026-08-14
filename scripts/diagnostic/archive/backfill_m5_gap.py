"""
ARCHIVED — historical record of a one-off backfill, not a general-purpose
tool. Fixed the specific m5 gap (2026-08-07 -> 08-11) caused by the
get_rates_incremental() truncation-direction bug (fixed in
scripts/sync/mt5_data_fetcher.py). The root cause is permanently fixed, so
this exact scenario won't recur — kept for reference, not for reuse. For a
future full re-sync need, see scripts/diagnostic/resync_intraday_pass_b.py
instead.

Fetches the exact missing range directly via get_rates() (no count cap)
and upserts into raw_gold.m5. Safe to re-run (ON DUPLICATE KEY UPDATE).

Usage: python scripts/diagnostic/archive/backfill_m5_gap.py
"""

import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from scripts.sync.mt5_data_fetcher import MT5DataFetcher  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "gold_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

GAP_START = "2026-08-07T23:55:00Z"
GAP_END = "2026-08-11T16:30:00Z"


def upsert_rows(conn, table, df):
    if df.empty:
        return 0
    rows = [
        {
            "date": r.time_utc.date(), "dt": r.time_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close),
            "v": int(r.tick_volume),
        }
        for r in df.itertuples()
    ]
    sql = f"""
    INSERT INTO `{table}`
        (price_date, price_datetime, open_price, high_price, low_price, close_price, volume, data_source)
    VALUES
        (%(date)s, %(dt)s, %(o)s, %(h)s, %(l)s, %(c)s, %(v)s, 'mt5')
    ON DUPLICATE KEY UPDATE
        open_price=VALUES(open_price), high_price=VALUES(high_price), low_price=VALUES(low_price),
        close_price=VALUES(close_price), volume=VALUES(volume), data_source=VALUES(data_source)
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def main():
    fetcher = MT5DataFetcher()
    fetcher.connect()
    try:
        fetcher.check_symbol("XAUUSD")
        df = fetcher.get_rates("XAUUSD", "M5", GAP_START, GAP_END)
        print(f"Fetched {len(df)} M5 bars for gap [{GAP_START} -> {GAP_END}]")
        if not df.empty:
            print("First:", df["time_utc"].iloc[0], " Last:", df["time_utc"].iloc[-1])

        conn = pymysql.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
            database="raw_gold", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            n = upsert_rows(conn, "m5", df)
            print(f"Upserted {n} rows into raw_gold.m5")
        finally:
            conn.close()
    finally:
        fetcher.disconnect()


if __name__ == "__main__":
    main()
