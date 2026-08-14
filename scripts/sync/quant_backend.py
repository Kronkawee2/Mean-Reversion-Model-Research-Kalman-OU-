"""
QuantBackend: orchestrates Step 1 Yahoo Finance sync for main.py and the
Airflow DAG (airflow/dags/quant_daily_sync.py).

Scope:
  - raw_gold, raw_eurusd: h4 + d1 only. m5/m15/h1 are MT5-owned via
    scripts/sync/scheduler/mt5_sync_service.py and are NOT touched here. h6
    is resampled from h1 elsewhere, not fetched.
  - raw_dxy, raw_us10y, raw_vix, raw_gdx: full scope per schema_raw.sql
    (dxy has h1+d1, the rest are d1-only).

This file previously did not exist in the repo even though main.py and the
Airflow DAG both imported it — that import was broken before this file was
added.
"""

import logging
import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fetcher.yahoo_finance_client import YahooFinanceClient  # noqa: E402
from fetcher.market_fetcher import MarketFetcher, MACRO_ASSET_TF  # noqa: E402

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "gold_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# asset -> (database, yfinance ticker, rounding decimals, reject-flat-OHLC)
# reject_flat_ohlc=True only for FX-precision instruments (see
# YahooFinanceClient.fetch_gold_data docstring) — gold's occasional
# legitimate flat quiet-day bars at 2-decimal precision must not be dropped.
GOLD_EURUSD_ASSETS = {
    "XAUUSD": ("raw_gold", "GC=F", 2, False),
    "EURUSD": ("raw_eurusd", "EURUSD=X", 5, True),
}
GOLD_EURUSD_TF = {"h4": "4h", "d1": "1d"}
GOLD_EURUSD_PERIOD = {"4h": "730d", "1d": "max"}


def _upsert_sql(table: str) -> str:
    return f"""
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


class QuantBackend:
    def __init__(self):
        self._conn_kwargs = dict(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        )
        self._conns = {}
        self.yahoo = YahooFinanceClient()
        self.market = MarketFetcher()

    def _conn(self, database: str):
        if database not in self._conns:
            self._conns[database] = pymysql.connect(database=database, **self._conn_kwargs)
        return self._conns[database]

    def _upsert(self, database: str, table: str, records: list) -> int:
        if not records:
            return 0
        rows = [
            {
                "date": r["date"],
                "dt": r["datetime"],
                "o": r["open"],
                "h": r["high"],
                "l": r["low"],
                "c": r["close"],
                "v": r["volume"],
            }
            for r in records
        ]
        conn = self._conn(database)
        with conn.cursor() as cur:
            cur.executemany(_upsert_sql(table), rows)
        conn.commit()
        return len(rows)

    def _sync_gold_eurusd(self) -> dict:
        results = {}
        for asset_name, (db_name, ticker_sym, decimals, reject_flat) in GOLD_EURUSD_ASSETS.items():
            for table, interval in GOLD_EURUSD_TF.items():
                period = GOLD_EURUSD_PERIOD[interval]
                records = self.yahoo.fetch_gold_data(
                    ticker_sym, period=period, interval=interval,
                    decimals=decimals, reject_flat_ohlc=reject_flat,
                )
                n = self._upsert(db_name, table, records)
                results[f"{db_name}.{table}"] = n
                logger.info(f"{asset_name} [{table}]: upserted {n} rows")
        return results

    def _sync_macro(self) -> dict:
        results = {}
        for asset_name, timeframes in MACRO_ASSET_TF.items():
            db_name = f"raw_{asset_name.lower()}"
            for table in timeframes:
                records = self.market.fetch_market_data(asset_name, table)
                n = self._upsert(db_name, table, records)
                results[f"{db_name}.{table}"] = n
                logger.info(f"{asset_name} [{table}]: upserted {n} rows")
        return results

    def sync_all(self) -> dict:
        logger.info("QuantBackend.sync_all() starting")
        results = {}
        results.update(self._sync_gold_eurusd())
        results.update(self._sync_macro())
        logger.info(f"QuantBackend.sync_all() done: {results}")
        return results

    def close(self):
        for conn in self._conns.values():
            conn.close()
        self._conns.clear()
