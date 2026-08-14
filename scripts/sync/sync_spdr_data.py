"""
Fetches SPDR GLD daily holdings data via SpdrFetcher and upserts into
raw_spdr.gld. Prints a summary report for manual sanity-checking against
spdrgoldshares.com's own published figures.

Usage:
    python scripts/sync/sync_spdr_data.py
    python scripts/sync/sync_spdr_data.py --no-write
"""

import argparse
import math
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fetcher.spdr_fetcher import SpdrFetcher  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")


def _conn():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database="raw_spdr", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def upsert(records: list) -> int:
    if not records:
        return 0
    sql = """
    INSERT INTO gld
        (report_date, closing_price, ounces_per_share, nav_per_share_1030, indicative_price_415,
         bid_ask_midpoint_415, premium_discount_pct, daily_share_volume,
         total_ounces_in_trust, tonnes_of_gold, total_nav)
    VALUES
        (%(report_date)s, %(closing_price)s, %(ounces_per_share)s, %(nav_per_share_1030)s, %(indicative_price_415)s,
         %(bid_ask_midpoint_415)s, %(premium_discount_pct)s, %(daily_share_volume)s,
         %(total_ounces_in_trust)s, %(tonnes_of_gold)s, %(total_nav)s)
    ON DUPLICATE KEY UPDATE
        closing_price = VALUES(closing_price), ounces_per_share = VALUES(ounces_per_share),
        nav_per_share_1030 = VALUES(nav_per_share_1030), indicative_price_415 = VALUES(indicative_price_415),
        bid_ask_midpoint_415 = VALUES(bid_ask_midpoint_415), premium_discount_pct = VALUES(premium_discount_pct),
        daily_share_volume = VALUES(daily_share_volume),
        total_ounces_in_trust = VALUES(total_ounces_in_trust), tonnes_of_gold = VALUES(tonnes_of_gold),
        total_nav = VALUES(total_nav)
    """
    numeric_cols = [
        "closing_price", "ounces_per_share", "nav_per_share_1030", "indicative_price_415",
        "bid_ask_midpoint_415", "premium_discount_pct", "daily_share_volume",
        "total_ounces_in_trust", "tonnes_of_gold", "total_nav",
    ]
    for row in records:
        for key in numeric_cols:
            val = row.get(key)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                row[key] = None

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
    print(f"Last {n} reports:")
    for r in records[-n:]:
        print(
            f"  {r['report_date']}  price={r['closing_price']}  "
            f"tonnes={r['tonnes_of_gold']}  ounces_in_trust={r['total_ounces_in_trust']:,.2f}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    fetcher = SpdrFetcher()
    records = fetcher.fetch_history()
    print_report(records)

    if not args.no_write:
        n = upsert(records)
        print(f"\nUpserted {n} records into `raw_spdr`.gld")


if __name__ == "__main__":
    main()
