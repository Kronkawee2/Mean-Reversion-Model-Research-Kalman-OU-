"""
Fetches Fed Funds Rate (DFF) and 10Y TIPS real yield (DFII10) via
FredFetcher and upserts into raw_fred.fed_funds / raw_fred.tips10y.
Prints a summary report for manual sanity-checking against
fred.stlouisfed.org's own published figures.

Usage:
    python scripts/sync/sync_fred_data.py
    python scripts/sync/sync_fred_data.py --no-write
"""

import argparse
import math
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fetcher.fred_fetcher import FredFetcher  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# series_id -> (target table, value column)
SERIES_TABLE = {
    "DFF": ("fed_funds", "rate_pct"),
    "DFII10": ("tips10y", "real_yield_pct"),
    "CPIAUCSL": ("cpi", "cpi_index"),
}


def _conn():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database="raw_fred", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def upsert(table: str, value_col: str, records: list) -> int:
    if not records:
        return 0
    sql = f"""
    INSERT INTO `{table}` (report_date, {value_col})
    VALUES (%(report_date)s, %({value_col})s)
    ON DUPLICATE KEY UPDATE {value_col} = VALUES({value_col})
    """
    for row in records:
        val = row.get(value_col)
        if val is None or (isinstance(val, float) and math.isnan(val)):
            row[value_col] = None

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, records)
        conn.commit()
    finally:
        conn.close()
    return len(records)


def print_report(series_id: str, value_col: str, records: list, n: int = 5):
    print(f"\n{series_id}: {len(records)} records")
    if not records:
        return
    print(f"Date range: {records[0]['report_date']} -> {records[-1]['report_date']}")
    print(f"Last {n} days:")
    for r in records[-n:]:
        print(f"  {r['report_date']}  {value_col}={r[value_col]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    fetcher = FredFetcher()
    for series_id, (table, value_col) in SERIES_TABLE.items():
        records = fetcher.fetch_series(series_id)
        print_report(series_id, value_col, records)

        if not args.no_write:
            n = upsert(table, value_col, records)
            print(f"Upserted {n} records into `raw_fred`.{table}")


if __name__ == "__main__":
    main()
