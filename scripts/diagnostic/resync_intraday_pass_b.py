"""
Pass B of the timezone data-integrity workstream: re-syncs raw intraday
tables using the corrected fetchers (Pass A). Fetches ALL new data into
memory first and sanity-checks it BEFORE deleting anything, so a fetch
failure or garbage result never leaves a table empty.

Kept as a reusable tool, not a one-off — this is the pattern to reach for
if raw MT5/Yahoo intraday data ever needs a full corrective re-sync again
(e.g. after another upstream data bug). It IS destructive (deletes and
replaces whole tables), so don't run it casually.

Scope (per quant_backend.py's documented ownership):
  - MT5-owned: raw_gold/raw_eurusd h1, m15, m5
  - Yahoo-owned intraday: raw_dxy.h1
  - d1 tables are NOT touched here (Pass B step 2: spot-check only)

STALE as of the h4 MT5-switch decision (see docs/DECISIONS.md): the
gold_h4/eurusd_h4 fetch+replace steps below still exist in this file but
target a now-deprecated table (raw_gold.h4/raw_eurusd.h4 are no longer
read by anything -- CRT equilibrium/features/dashboard all resample h4
from MT5 h1 instead). Re-running this script as-is would repopulate a
table nothing consumes anymore. Left unedited since this is a historical,
already-completed diagnostic tool, not part of the live pipeline -- if
this script is ever reused, drop the gold_h4/eurusd_h4 steps first.

Usage: python scripts/diagnostic/resync_intraday_pass_b.py
"""

import datetime
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.sync.mt5_data_fetcher import MT5DataFetcher  # noqa: E402
from fetcher.yahoo_finance_client import YahooFinanceClient  # noqa: E402
from fetcher.market_fetcher import MarketFetcher  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "gold_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

MT5_LOOKBACK_DAYS = {"H1": 700, "M15": 180, "M5": 90}
MT5_TABLE = {"H1": "h1", "M15": "m15", "M5": "m5"}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def fetch_mt5(fetcher, symbol, db_name):
    now = datetime.datetime.now(datetime.timezone.utc)
    out = {}
    for tf, days_back in MT5_LOOKBACK_DAYS.items():
        start = now - datetime.timedelta(days=days_back)
        df = fetcher.get_rates(symbol, tf, start, now, chunk_days=30)
        out[MT5_TABLE[tf]] = df
        print(f"  [fetch] {db_name}.{MT5_TABLE[tf]}: {len(df)} rows "
              f"({df['time_utc'].min()} -> {df['time_utc'].max()})" if not df.empty else f"  [fetch] {db_name}.{MT5_TABLE[tf]}: EMPTY")
    return out


def mt5_rows_to_records(df):
    return [
        {
            "date": r.time_utc.date(), "dt": r.time_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "o": float(r.open), "h": float(r.high), "l": float(r.low), "c": float(r.close),
            "v": int(r.tick_volume),
        }
        for r in df.itertuples()
    ]


def replace_table(db_name, table, records, source_col=True):
    conn = _conn(db_name)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) c FROM `{table}`")
            before = cur.fetchone()["c"]
            cur.execute(f"DELETE FROM `{table}`")
            if records:
                if source_col:
                    sql = f"""
                    INSERT INTO `{table}`
                        (price_date, price_datetime, open_price, high_price, low_price, close_price, volume, data_source)
                    VALUES
                        (%(date)s, %(dt)s, %(o)s, %(h)s, %(l)s, %(c)s, %(v)s, 'mt5')
                    """
                else:
                    sql = f"""
                    INSERT INTO `{table}`
                        (price_date, price_datetime, open_price, high_price, low_price, close_price, volume)
                    VALUES
                        (%(date)s, %(dt)s, %(o)s, %(h)s, %(l)s, %(c)s, %(v)s)
                    """
                cur.executemany(sql, records)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) c FROM `{table}`")
            after = cur.fetchone()["c"]
    finally:
        conn.close()
    print(f"  [write] {db_name}.{table}: {before} -> {after} rows")
    return before, after


def main():
    print("=" * 70)
    print("STEP 1: fetch corrected MT5 data into memory (gold + eurusd, h1/m15/m5)")
    print("=" * 70)
    fetcher = MT5DataFetcher()
    fetcher.connect()
    fetcher.check_symbol("XAUUSD")
    gold_mt5 = fetch_mt5(fetcher, "XAUUSD", "raw_gold")
    fetcher.check_symbol("EURUSD")
    eurusd_mt5 = fetch_mt5(fetcher, "EURUSD", "raw_eurusd")
    fetcher.disconnect()

    print()
    print("=" * 70)
    print("STEP 2: fetch corrected Yahoo data into memory (gold/eurusd h4, dxy h1)")
    print("=" * 70)
    yahoo = YahooFinanceClient()
    market = MarketFetcher()
    gold_h4 = yahoo.fetch_gold_data("GC=F", period="730d", interval="4h", decimals=2, reject_flat_ohlc=False)
    print(f"  [fetch] raw_gold.h4: {len(gold_h4)} records")
    eurusd_h4 = yahoo.fetch_gold_data("EURUSD=X", period="730d", interval="4h", decimals=5, reject_flat_ohlc=True)
    print(f"  [fetch] raw_eurusd.h4: {len(eurusd_h4)} records")
    dxy_h1 = market.fetch_market_data("DXY", "h1")
    print(f"  [fetch] raw_dxy.h1: {len(dxy_h1)} records")

    print()
    print("=" * 70)
    print("STEP 3: sanity check before any deletes")
    print("=" * 70)
    problems = []
    if gold_mt5["h1"].empty or len(gold_mt5["h1"]) < 100:
        problems.append("raw_gold.h1 fetch returned too few rows")
    if eurusd_mt5["h1"].empty or len(eurusd_mt5["h1"]) < 100:
        problems.append("raw_eurusd.h1 fetch returned too few rows")
    if not gold_h4:
        problems.append("raw_gold.h4 fetch returned nothing")
    if not eurusd_h4:
        problems.append("raw_eurusd.h4 fetch returned nothing")
    if not dxy_h1:
        problems.append("raw_dxy.h1 fetch returned nothing")

    if problems:
        print("ABORTING -- refusing to delete existing data:")
        for p in problems:
            print("  -", p)
        return

    print("  All fetches look sane. Proceeding to delete + replace.")

    print()
    print("=" * 70)
    print("STEP 4: delete + replace (MT5 tables)")
    print("=" * 70)
    # raw_eurusd's m5/m15/h1 schema (storage/schema_raw.sql) never included a
    # data_source column -- EURUSD was never MT5-synced before this pass, so
    # nobody added it. Not something to "fix" here (separate, pre-existing
    # schema inconsistency, unrelated to the timezone work) -- just match
    # each table's actual columns.
    for db_name, tf_data, has_source_col in (("raw_gold", gold_mt5, True), ("raw_eurusd", eurusd_mt5, False)):
        for table, df in tf_data.items():
            records = mt5_rows_to_records(df)
            replace_table(db_name, table, records, source_col=has_source_col)

    print()
    print("=" * 70)
    print("STEP 5: delete + replace (Yahoo tables)")
    print("=" * 70)
    def yahoo_records_to_rows(records):
        return [{"date": r["date"], "dt": r["datetime"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]} for r in records]

    replace_table("raw_gold", "h4", yahoo_records_to_rows(gold_h4), source_col=False)
    replace_table("raw_eurusd", "h4", yahoo_records_to_rows(eurusd_h4), source_col=False)
    replace_table("raw_dxy", "h1", yahoo_records_to_rows(dxy_h1), source_col=False)

    print()
    print("Pass B resync complete.")


if __name__ == "__main__":
    main()
