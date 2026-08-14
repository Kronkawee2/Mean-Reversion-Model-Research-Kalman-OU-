"""
Fetches CFTC Legacy COT report data (gold + EUR) via CotFetcher and
upserts into raw_cot.gold / raw_cot.eur. Prints a summary report for
manual sanity-checking against CFTC.gov's own published figures.

Usage:
    python scripts/sync/sync_cot_data.py
    python scripts/sync/sync_cot_data.py --market gold --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fetcher.cot_fetcher import CotFetcher  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

MARKET_TABLE = {"gold": "gold", "eur": "eur"}


def _conn():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database="raw_cot", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def upsert(market: str, records: list) -> int:
    if not records:
        return 0
    table = MARKET_TABLE[market]
    sql = f"""
    INSERT INTO `{table}`
        (report_date, open_interest_all, noncommercial_long, noncommercial_short,
         noncommercial_spreading, commercial_long, commercial_short,
         nonreportable_long, nonreportable_short, commercial_net_position, noncommercial_net_position)
    VALUES
        (%(report_date)s, %(open_interest_all)s, %(noncommercial_long)s, %(noncommercial_short)s,
         %(noncommercial_spreading)s, %(commercial_long)s, %(commercial_short)s,
         %(nonreportable_long)s, %(nonreportable_short)s, %(commercial_net_position)s, %(noncommercial_net_position)s)
    ON DUPLICATE KEY UPDATE
        open_interest_all = VALUES(open_interest_all),
        noncommercial_long = VALUES(noncommercial_long), noncommercial_short = VALUES(noncommercial_short),
        noncommercial_spreading = VALUES(noncommercial_spreading),
        commercial_long = VALUES(commercial_long), commercial_short = VALUES(commercial_short),
        nonreportable_long = VALUES(nonreportable_long), nonreportable_short = VALUES(nonreportable_short),
        commercial_net_position = VALUES(commercial_net_position),
        noncommercial_net_position = VALUES(noncommercial_net_position)
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, records)
        conn.commit()
    finally:
        conn.close()
    return len(records)


def print_report(market: str, records: list, n: int = 5):
    print(f"\n[{market}] Total records: {len(records)}")
    if not records:
        return
    print(f"[{market}] Date range: {records[0]['report_date']} -> {records[-1]['report_date']}")
    print(f"[{market}] Last {n} reports:")
    for r in records[-n:]:
        print(
            f"  {r['report_date']}  OI={r['open_interest_all']:,}  "
            f"comm_net={r['commercial_net_position']:,}  noncomm_net={r['noncommercial_net_position']:,}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="all", choices=["gold", "eur", "all"])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    markets = ["gold", "eur"] if args.market == "all" else [args.market]
    fetcher = CotFetcher()

    for market in markets:
        print(f"\n=== COT {market} ===")
        records = fetcher.fetch_market_history(market)
        print_report(market, records)
        if not args.no_write:
            n = upsert(market, records)
            print(f"[{market}] Upserted {n} records into `raw_cot`.{MARKET_TABLE[market]}")


if __name__ == "__main__":
    main()
