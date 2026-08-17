"""
Fetches the euro area 10Y AAA yield curve spot rate via EcbFetcher and
upserts into raw_ecb.eu10y. Prints a summary report for manual
sanity-checking against the ECB Data Portal's own published figures.

Usage:
    python scripts/sync/sync_ecb_data.py
    python scripts/sync/sync_ecb_data.py --no-write
"""

import argparse
import math
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fetcher.ecb_fetcher import EcbFetcher  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")


def _conn():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database="raw_ecb", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def upsert(records: list) -> int:
    if not records:
        return 0
    sql = """
    INSERT INTO eu10y (report_date, yield_pct)
    VALUES (%(report_date)s, %(yield_pct)s)
    ON DUPLICATE KEY UPDATE yield_pct = VALUES(yield_pct)
    """
    for row in records:
        val = row.get("yield_pct")
        if val is None or (isinstance(val, float) and math.isnan(val)):
            row["yield_pct"] = None

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, records)
        conn.commit()
    finally:
        conn.close()
    return len(records)


def print_report(records: list, n: int = 5):
    print(f"\nTotal records: {len(records)}")
    if not records:
        return
    print(f"Date range: {records[0]['report_date']} -> {records[-1]['report_date']}")
    print(f"Last {n} days:")
    for r in records[-n:]:
        print(f"  {r['report_date']}  yield_pct={r['yield_pct']:.4f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    fetcher = EcbFetcher()
    records = fetcher.fetch_series()
    print_report(records)

    if not args.no_write:
        n = upsert(records)
        print(f"\nUpserted {n} records into `raw_ecb`.eu10y")


if __name__ == "__main__":
    main()
