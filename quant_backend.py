"""
Quant Trader Multi-Timeframe Backend (v3)
Grouped by symbol: each symbol = 1 database
  gold/   -> m5, m15, h1, h4, h6, d1, signals, daily_summary
  eurusd/ -> m5, m15, h1, h4, h6, d1, signals, daily_summary
"""

import os
import sys
import time
import pymysql
import pymysql.cursors
import pandas as pd
import logging
from pathlib import Path
from typing import List, Dict
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger("QuantBackend")


# ── Configuration ─────────────────────────────────────────────

SYMBOLS = {
    "gold":   {"yahoo": "GC=F",     "label": "Gold (XAUUSD)"},
    "eurusd": {"yahoo": "EURUSD=X", "label": "EUR/USD"},
}

# TF label -> table name mapping
TF_TABLES = {
    "5m": "m5", "15m": "m15", "1h": "h1",
    "4h": "h4", "6h": "h6", "1d": "d1",
}

YAHOO_CONFIG = {
    "5m":  {"interval": "5m",  "period": "60d"},
    "15m": {"interval": "15m", "period": "60d"},
    "1h":  {"interval": "1h",  "period": "730d"},
    "4h":  {"resample_from": "1h", "rule": "4h"},
    "6h":  {"resample_from": "1h", "rule": "6h"},
    "1d":  {"interval": "1d",  "period": "5y"},
}


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return df
    return df.resample(rule).agg({
        'Open': 'first', 'High': 'max',
        'Low': 'min', 'Close': 'last', 'Volume': 'sum',
    }).dropna(subset=['Open'])


class QuantDB:
    """Manages per-symbol databases (gold, eurusd)."""

    def __init__(self):
        self.host = os.getenv('DB_HOST', 'localhost')
        self.port = int(os.getenv('DB_PORT', 3306))
        self.user = os.getenv('DB_USER', 'root')
        self.password = os.getenv('DB_PASSWORD', '')
        self._connections = {}

    def _get_conn(self, db_name: str):
        if db_name not in self._connections or not self._connections[db_name].open:
            self._connections[db_name] = pymysql.connect(
                host=self.host, port=self.port,
                user=self.user, password=self.password,
                database=db_name, charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor, autocommit=False
            )
        return self._connections[db_name]

    def init_schema(self):
        """Create databases and tables from schema_quant.sql."""
        schema_path = Path(__file__).parent / "storage" / "schema_quant.sql"
        if not schema_path.exists():
            logger.error(f"Schema not found: {schema_path}")
            return False

        with open(schema_path, 'r', encoding='utf-8') as f:
            sql = f.read()

        # Use root-level connection (no specific DB) to run full schema
        conn = pymysql.connect(
            host=self.host, port=self.port,
            user=self.user, password=self.password,
            charset='utf8mb4'
        )
        cursor = conn.cursor()
        current_db = None

        for stmt in sql.split(';'):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                if stmt.upper().startswith('USE '):
                    current_db = stmt.split()[-1].strip('`')
                cursor.execute(stmt)
                conn.commit()
            except pymysql.err.OperationalError as e:
                if 'already exists' in str(e):
                    continue
                raise

        cursor.close()
        conn.close()
        logger.info("Schema initialized (databases: gold, eurusd)")
        return True

    def insert_prices(self, db_name: str, table: str, records: List[Dict]) -> int:
        if not records:
            return 0
        conn = self._get_conn(db_name)
        cursor = conn.cursor()
        inserted = 0
        for r in records:
            try:
                cursor.execute(f"""
                    INSERT INTO `{table}`
                    (price_date, price_datetime, open_price, high_price, low_price, close_price, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        open_price=VALUES(open_price), high_price=VALUES(high_price),
                        low_price=VALUES(low_price), close_price=VALUES(close_price),
                        volume=VALUES(volume)
                """, (r['date'], r['datetime'], r['open'], r['high'], r['low'], r['close'], r['volume']))
                inserted += 1
            except pymysql.err.IntegrityError:
                pass
        conn.commit()
        cursor.close()
        return inserted

    def get_prices(self, db_name: str, table: str, limit: int = 100) -> pd.DataFrame:
        conn = self._get_conn(db_name)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT price_date, price_datetime, open_price, high_price, low_price, close_price, volume
            FROM `{table}` ORDER BY price_datetime DESC LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        cursor.close()
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values('price_datetime').reset_index(drop=True)
        return df

    def get_overview(self) -> pd.DataFrame:
        results = []
        for db_name in SYMBOLS:
            conn = self._get_conn(db_name)
            cursor = conn.cursor()
            for tf_label, tbl in TF_TABLES.items():
                try:
                    cursor.execute(f"SELECT COUNT(*) AS cnt, MIN(price_date) AS first_date, MAX(price_date) AS last_date FROM `{tbl}`")
                    row = cursor.fetchone()
                    results.append({
                        'database': db_name,
                        'table': tbl,
                        'records': row['cnt'],
                        'first_date': row['first_date'],
                        'last_date': row['last_date'],
                    })
                except Exception:
                    results.append({'database': db_name, 'table': tbl, 'records': 0, 'first_date': None, 'last_date': None})
            cursor.close()
        return pd.DataFrame(results)

    def close(self):
        for name, conn in self._connections.items():
            if conn.open:
                conn.close()
        logger.info("All connections closed")


class QuantBackend:
    """Multi-Timeframe Data Engine."""

    def __init__(self):
        self.db = QuantDB()
        self.db.init_schema()
        import yfinance as yf
        self.yf = yf

    def _fetch(self, yahoo_sym: str, interval: str, period: str) -> pd.DataFrame:
        try:
            df = self.yf.Ticker(yahoo_sym).history(period=period, interval=interval)
            if df.empty:
                logger.warning(f"No data: {yahoo_sym} {interval}")
            return df
        except Exception as e:
            logger.error(f"Fetch error: {yahoo_sym} {interval} - {e}")
            return pd.DataFrame()

    def _to_records(self, df: pd.DataFrame) -> List[Dict]:
        records = []
        for idx, row in df.iterrows():
            records.append({
                'datetime': idx.strftime('%Y-%m-%d %H:%M:%S'),
                'date': idx.strftime('%Y-%m-%d'),
                'open': round(float(row['Open']), 5),
                'high': round(float(row['High']), 5),
                'low': round(float(row['Low']), 5),
                'close': round(float(row['Close']), 5),
                'volume': int(row['Volume']) if pd.notna(row['Volume']) else 0,
            })
        return records

    def sync_symbol(self, sym_key: str) -> Dict[str, int]:
        yahoo_sym = SYMBOLS[sym_key]["yahoo"]
        results = {}
        h1_df = None

        for tf_label, cfg in YAHOO_CONFIG.items():
            tbl = TF_TABLES[tf_label]

            if "interval" in cfg:
                logger.info(f"  [{sym_key}] {tbl} <- fetching...")
                df = self._fetch(yahoo_sym, cfg["interval"], cfg["period"])
                if df.empty:
                    results[tbl] = 0
                    continue
                if cfg["interval"] == "1h":
                    h1_df = df.copy()
                records = self._to_records(df)
                inserted = self.db.insert_prices(sym_key, tbl, records)
                results[tbl] = inserted
                logger.info(f"  [{sym_key}] {tbl} -> {inserted} records")

            elif "resample_from" in cfg:
                if h1_df is None or h1_df.empty:
                    results[tbl] = 0
                    continue
                logger.info(f"  [{sym_key}] {tbl} <- resampling from h1...")
                resampled = resample_ohlcv(h1_df, cfg["rule"])
                records = self._to_records(resampled)
                inserted = self.db.insert_prices(sym_key, tbl, records)
                results[tbl] = inserted
                logger.info(f"  [{sym_key}] {tbl} -> {inserted} records (resampled)")

        return results

    def sync_all(self) -> Dict[str, Dict[str, int]]:
        all_results = {}
        for sym_key, info in SYMBOLS.items():
            logger.info(f"\n{'='*50}")
            logger.info(f"  {info['label']} ({info['yahoo']})")
            logger.info(f"{'='*50}")
            all_results[sym_key] = self.sync_symbol(sym_key)
            time.sleep(1)
        return all_results

    def close(self):
        self.db.close()


# ── CLI ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print()
    print("=" * 55)
    print("  QUANT TRADER - Data Engine v3")
    print("-" * 55)
    print("  gold/   m5 | m15 | h1 | h4 | h6 | d1")
    print("  eurusd/ m5 | m15 | h1 | h4 | h6 | d1")
    print("=" * 55)

    backend = QuantBackend()
    results = backend.sync_all()

    print()
    print("=" * 55)
    print("  SYNC RESULTS")
    print("=" * 55)
    for sym_key, tf_results in results.items():
        label = SYMBOLS[sym_key]["label"]
        print(f"\n  {label} (database: {sym_key})")
        for tbl, count in tf_results.items():
            status = f"{count:>7,} records" if count > 0 else "      - no data"
            print(f"    {tbl:6s}  {status}")

    print()
    print("=" * 55)
    print("  DATABASE OVERVIEW")
    print("=" * 55)
    overview = backend.db.get_overview()
    if not overview.empty:
        print()
        print(overview.to_string(index=False))

    for sym_key in SYMBOLS:
        print(f"\n  Latest 3 from {sym_key}/d1:")
        df = backend.db.get_prices(sym_key, "d1", limit=3)
        if not df.empty:
            for _, row in df.iterrows():
                print(f"    {row['price_date']}  O:{float(row['open_price']):>10.5f}"
                      f"  H:{float(row['high_price']):>10.5f}"
                      f"  L:{float(row['low_price']):>10.5f}"
                      f"  C:{float(row['close_price']):>10.5f}")

    backend.close()
    print("\nDone.")
