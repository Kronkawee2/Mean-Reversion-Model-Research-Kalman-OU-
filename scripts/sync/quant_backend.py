"""
QuantBackend: orchestrates Step 1 Yahoo Finance sync for main.py.

Scope:
  - raw_gold, raw_eurusd: NOTHING is synced here anymore -- m5/m15/h1 are
    MT5-owned via scripts/sync/scheduler/mt5_sync_service.py, and h4/h6/d1
    are all resampled from h1 elsewhere, not fetched. d1 (and h4 before it)
    USED to be fetched here (Yahoo GC=F/EURUSD=X) until the MT5-migration
    decisions: Yahoo's h4/d1 candles turned out to be anchored to
    America/New_York local time rather than fixed UTC, so 27.8% of gold's
    h4 rows and 36.1%/58.3% of gold's/eurusd's d1 rows sat on a
    DST-shifted grid every Nov-Mar. Cost/benefit analysis showed near-zero
    computational impact from dropping Yahoo h4/d1 (the 2-year rolling
    window already in effect elsewhere means nothing reads pre-2024-09
    history in practice; see docs/DECISIONS.md), so both were deprecated
    in favor of resampling from MT5's already-UTC-correct h1 -- same
    approach h6 already used. This closes the full MT5 migration for
    XAUUSD/EURUSD across every timeframe (m5/m15/h1/h4/h6/d1).
    raw_gold.{h4,d1}/raw_eurusd.{h4,d1} still exist with their old
    Yahoo-sourced rows (not deleted, just no longer written to) -- nothing
    reads them anymore.
  - raw_us10y, raw_gdx: d1-only, still Yahoo-sourced (^TNX, GDX) -- no MT5
    equivalent exists (no bond/yield instrument, no gold-miner ETF on
    Eightcap), confirmed via a live terminal symbol check, see
    docs/DECISIONS.md.
  - raw_dxy, raw_vix, raw_silver: Yahoo sync (DX-Y.NYB/^VIX/SI=F) retired
    as of the Silver/DXY/VIX MT5-migration decision -- MT5-tradeable
    equivalents (USDX/VIX/XAGUSD) exist and were confirmed live on the
    Eightcap terminal. h1 now comes from MT5 (raw_dxy.h1/raw_vix.h1/
    raw_silver.h1, synced the same way as gold/eurusd's h1), and d1 for
    the two divergence-model consumers (DXY, Silver) is resampled from
    that h1 in run_intermarket_divergence_detection.py, same pattern as
    gold/eurusd's own d1. Their old raw_*.d1 Yahoo tables still exist
    (not deleted, just no longer written to or read from) -- same
    DST-anchoring bug found in gold/eurusd's h4/d1 was confirmed present
    here too (and, for DXY specifically, a separate near-total
    row-duplication bug), fixed by this migration for the MT5-sourced
    portion going forward; the old Yahoo history is left as-is.

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

from fetcher.market_fetcher import MarketFetcher, MACRO_ASSET_TF  # noqa: E402

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "gold_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")



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
        results.update(self._sync_macro())
        logger.info(f"QuantBackend.sync_all() done: {results}")
        return results

    def close(self):
        for conn in self._conns.values():
            conn.close()
        self._conns.clear()
