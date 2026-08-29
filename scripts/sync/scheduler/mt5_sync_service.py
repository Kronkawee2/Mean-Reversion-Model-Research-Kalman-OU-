"""
MT5 -> MySQL sync service (Phase 0.5). Standalone Windows process, independent
of Airflow (Airflow can't import the MetaTrader5 package). Polls closed
candles from MT5DataFetcher for whichever symbol MT5_SYMBOL selects and
upserts them into that symbol's own raw_* database. XAUUSD/EURUSD sync
M5/M15/H1 with data_source='mt5'; the three macro drivers added by the
Silver/DXY/VIX MT5-migration decision (XAGUSD/USDX/VIX, see
docs/DECISIONS.md) sync H1 only, into tables with no data_source column.

The destination database is derived from SYMBOL (RAW_DB[SYMBOL]), not a
separate hardcoded constant -- this project has been bitten before by
exactly this class of bug (a hardcoded destination not actually wired to
the thing that's supposed to select it), so this is deliberately built the
same way as every other symbol-aware script in the project (see the
RAW_DB dict convention used throughout scripts/detection/).

Usage:
    python scripts/sync/scheduler/mt5_sync_service.py            # long-lived loop
    python scripts/sync/scheduler/mt5_sync_service.py --once      # single cycle (e.g. for Windows Task Scheduler)
    python scripts/sync/scheduler/mt5_sync_service.py --interval 60 --debug

Requires: requirements-mt5.txt (MetaTrader5, pandas, python-dotenv, pymysql).
Installing that one file is sufficient to run this script standalone.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from scripts.sync.mt5_data_fetcher import (  # noqa: E402
    MT5DataFetcher,
    MT5ConnectionError,
    MT5LoginError,
    MT5DataError,
    MT5SymbolError,
)

load_dotenv()

logger = logging.getLogger("mt5_sync_service")

SYMBOL = os.environ.get("MT5_SYMBOL", "XAUUSD")
TIMEFRAME_TABLE = {"M5": "m5", "M15": "m15", "H1": "h1"}
RAW_DB = {
    "XAUUSD": "raw_gold", "EURUSD": "raw_eurusd", "NDX100": "raw_ndx100",
    # Macro drivers added by the Silver/DXY/VIX MT5-migration decision (see
    # docs/DECISIONS.md) -- h1-only (schema has no m5/m15 tables for these,
    # and nothing downstream needs finer than h1 for a macro driver
    # resampled to d1). Their h1 tables also have no data_source column
    # (unlike gold/eurusd's), matching raw_dxy.h1's pre-existing schema.
    "XAGUSD": "raw_silver", "USDX": "raw_dxy", "VIX": "raw_vix",
}
# Full M5/M15/H1 sync only for the two tradeable primary symbols; macro
# drivers only need H1 (their d1 is resampled from it downstream).
MACRO_SYMBOLS = {"XAGUSD", "USDX", "VIX"}
TIMEFRAMES = ["H1"] if SYMBOL in MACRO_SYMBOLS else ["M5", "M15", "H1"]
if SYMBOL not in RAW_DB:
    raise ValueError(f"MT5_SYMBOL={SYMBOL!r} has no known raw database mapping -- add it to RAW_DB before running")
TARGET_DB = RAW_DB[SYMBOL]
PIPELINE_NAME = "mt5_sync"

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "gold_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

BOOTSTRAP_COUNT = 500  # bars fetched when a table has no MT5 data yet


def retry_with_backoff(func, *, max_attempts=5, base_delay=2, exceptions):
    attempt = 0
    while True:
        attempt += 1
        try:
            return func()
        except exceptions as e:
            if attempt >= max_attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "Attempt %d/%d failed (%s), retrying in %ds",
                attempt, max_attempts, e, delay,
            )
            time.sleep(delay)


def connect_mysql():
    def _connect():
        return pymysql.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
            database=TARGET_DB, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        )
    return retry_with_backoff(_connect, exceptions=(pymysql.MySQLError,))


def connect_mt5():
    fetcher = MT5DataFetcher()

    def _connect():
        fetcher.connect()
        return fetcher

    return retry_with_backoff(
        _connect, exceptions=(MT5ConnectionError, MT5LoginError)
    )


def get_latest_datetime(conn, table: str):
    with conn.cursor() as cur:
        cur.execute(f"SELECT MAX(price_datetime) AS mx FROM `{table}`")
        row = cur.fetchone()
        return row["mx"] if row and row["mx"] else None


def upsert_rows(conn, table: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = [
        {
            "date": r.time_utc.date(),
            "dt": r.time_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "o": float(r.open),
            "h": float(r.high),
            "l": float(r.low),
            "c": float(r.close),
            "v": int(r.tick_volume),
        }
        for r in df.itertuples()
    ]
    # Macro-driver h1 tables (raw_dxy/raw_vix/raw_silver) have no
    # data_source column -- they predate that gold/eurusd-only convention
    # (raw_dxy.h1 in particular used to hold Yahoo data before this
    # symbol's migration, see docs/DECISIONS.md) -- so branch on TARGET_DB
    # rather than assume every h1/m5/m15 table has it.
    has_source_col = TARGET_DB not in ("raw_dxy", "raw_vix", "raw_silver")
    if has_source_col:
        sql = f"""
        INSERT INTO `{table}`
            (price_date, price_datetime, open_price, high_price, low_price, close_price, volume, data_source)
        VALUES
            (%(date)s, %(dt)s, %(o)s, %(h)s, %(l)s, %(c)s, %(v)s, 'mt5')
        ON DUPLICATE KEY UPDATE
            open_price  = VALUES(open_price),
            high_price  = VALUES(high_price),
            low_price   = VALUES(low_price),
            close_price = VALUES(close_price),
            volume      = VALUES(volume),
            data_source = VALUES(data_source)
        """
    else:
        sql = f"""
        INSERT INTO `{table}`
            (price_date, price_datetime, open_price, high_price, low_price, close_price, volume)
        VALUES
            (%(date)s, %(dt)s, %(o)s, %(h)s, %(l)s, %(c)s, %(v)s)
        ON DUPLICATE KEY UPDATE
            open_price  = VALUES(open_price),
            high_price  = VALUES(high_price),
            low_price   = VALUES(low_price),
            close_price = VALUES(close_price),
            volume      = VALUES(volume)
        """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def update_pipeline_status(conn, *, row_count=None, error=None):
    with conn.cursor() as cur:
        if error is None:
            cur.execute(
                """
                INSERT INTO pipeline_status (pipeline_name, last_success_at, last_row_count, last_error)
                VALUES (%s, NOW(), %s, NULL)
                ON DUPLICATE KEY UPDATE
                    last_success_at = NOW(),
                    last_row_count = VALUES(last_row_count),
                    last_error = NULL
                """,
                (PIPELINE_NAME, row_count),
            )
        else:
            cur.execute(
                """
                INSERT INTO pipeline_status (pipeline_name, last_success_at, last_row_count, last_error)
                VALUES (%s, NULL, NULL, %s)
                ON DUPLICATE KEY UPDATE
                    last_error = VALUES(last_error)
                """,
                (PIPELINE_NAME, str(error)[:2000]),
            )
    conn.commit()


def run_once() -> int:
    """Runs one sync cycle. Returns total rows upserted. Raises on failure."""
    fetcher = connect_mt5()
    conn = None
    try:
        conn = connect_mysql()
        fetcher.check_symbol(SYMBOL)

        total_rows = 0
        for tf in TIMEFRAMES:
            table = TIMEFRAME_TABLE[tf]
            latest = get_latest_datetime(conn, table)

            if latest is None:
                logger.info("%s/%s has no rows yet, bootstrapping %d bars", TARGET_DB, table, BOOTSTRAP_COUNT)
                df = fetcher.get_latest_rates(SYMBOL, tf, count=BOOTSTRAP_COUNT)
            else:
                last_ts = pd.Timestamp(latest, tz="UTC")
                df = fetcher.get_rates_incremental(SYMBOL, tf, last_ts, count=BOOTSTRAP_COUNT)

            n = upsert_rows(conn, table, df)
            total_rows += n
            logger.info("%s: upserted %d rows (latest bar: %s)", tf, n,
                        df["time_utc"].max() if not df.empty else "n/a")

        update_pipeline_status(conn, row_count=total_rows)
        return total_rows
    except (MT5DataError, MT5SymbolError, pymysql.MySQLError) as e:
        logger.error("Sync cycle failed: %s", e)
        if conn is not None:
            try:
                update_pipeline_status(conn, error=e)
            except pymysql.MySQLError:
                logger.exception("Failed to record pipeline_status error")
        raise
    finally:
        fetcher.disconnect()
        if conn is not None:
            conn.close()


def run_forever(interval_seconds: int):
    logger.info("Starting mt5_sync_service loop, interval=%ds, symbol=%s", interval_seconds, SYMBOL)
    while True:
        try:
            n = run_once()
            logger.info("Cycle complete: %d rows upserted", n)
        except Exception:
            logger.exception("Cycle failed, will retry next interval")
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="MT5 -> MySQL sync service")
    parser.add_argument("--once", action="store_true", help="run a single cycle and exit")
    parser.add_argument("--interval", type=int, default=60, help="seconds between cycles in loop mode")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.once:
        run_once()
    else:
        run_forever(args.interval)


if __name__ == "__main__":
    main()
