"""
Fetches the daily Geopolitical Risk Index via GprFetcher and upserts into
raw_gpr.gpr. Prints a summary report for manual sanity-checking against
matteoiacoviello.com's own published figures.

Usage:
    python scripts/sync/sync_gpr_data.py
    python scripts/sync/sync_gpr_data.py --no-write
"""

import argparse
import math
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fetcher.gpr_fetcher import GprFetcher  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")


def _conn():
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database="raw_gpr", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def upsert(records: list) -> int:
    if not records:
        return 0
    sql = """
    INSERT INTO gpr
        (report_date, gprd, gprd_act, gprd_threat, gprd_ma7, gprd_ma30)
    VALUES
        (%(report_date)s, %(gprd)s, %(gprd_act)s, %(gprd_threat)s, %(gprd_ma7)s, %(gprd_ma30)s)
    ON DUPLICATE KEY UPDATE
        gprd = VALUES(gprd), gprd_act = VALUES(gprd_act), gprd_threat = VALUES(gprd_threat),
        gprd_ma7 = VALUES(gprd_ma7), gprd_ma30 = VALUES(gprd_ma30)
    """
    numeric_cols = ["gprd", "gprd_act", "gprd_threat", "gprd_ma7", "gprd_ma30"]
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
    print(f"Last {n} days:")
    for r in records[-n:]:
        print(
            f"  {r['report_date']}  gprd={r['gprd']:.2f}  act={r['gprd_act']:.2f}  "
            f"threat={r['gprd_threat']:.2f}  ma7={r['gprd_ma7']:.2f}  ma30={r['gprd_ma30']:.2f}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    fetcher = GprFetcher()
    records = fetcher.fetch_history()
    print_report(records)

    if not args.no_write:
        n = upsert(records)
        print(f"\nUpserted {n} records into `raw_gpr`.gpr")


if __name__ == "__main__":
    main()
