"""
MySQL database connection and CRUD operations.
"""

import os
import logging
from typing import List, Dict
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

try:
    import pymysql
    import pymysql.cursors
except ImportError:
    pymysql = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


class DatabaseMySQL:
    """MySQL operations wrapper."""

    def __init__(self, host: str = None, port: int = None,
                 user: str = None, password: str = None,
                 database: str = None):
        if pymysql is None:
            raise ImportError("pymysql not installed. Run: pip install pymysql")

        self.host = host or os.getenv('DB_HOST', 'localhost')
        self.port = port or int(os.getenv('DB_PORT', 3306))
        self.user = user or os.getenv('DB_USER', 'root')
        self.password = password or os.getenv('DB_PASSWORD', '')
        self.database = database or os.getenv('DB_NAME', 'gold_yahoo_finance')

        self.conn = None
        self.connect()

    def connect(self):
        try:
            self.conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False
            )
            logger.info(f"Connected to MySQL at {self.host}:{self.port}/{self.database}")
        except pymysql.err.OperationalError as e:
            if 'Unknown database' in str(e):
                logger.info(f"Database '{self.database}' not found, creating...")
                self._create_database()
            else:
                logger.error(f"Failed to connect to MySQL: {e}")
                raise

    def _create_database(self):
        try:
            conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                charset='utf8mb4',
            )
            cursor = conn.cursor()
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self.database}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"Created database: {self.database}")

            self.conn = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False
            )
            logger.info(f"Connected to MySQL at {self.host}:{self.port}/{self.database}")
        except Exception as e:
            logger.error(f"Failed to create database: {e}")
            raise

    def close(self):
        if self.conn:
            self.conn.close()
            logger.info("MySQL connection closed")

    def init_schema(self):
        schema_path = Path(__file__).parent / "schema_mysql.sql"
        if not schema_path.exists():
            logger.error(f"Schema file not found: {schema_path}")
            return False

        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema_sql = f.read()

            cursor = self.conn.cursor()
            statements = [s.strip() for s in schema_sql.split(';') if s.strip()]
            for stmt in statements:
                if stmt.upper().startswith(('USE ', 'CREATE DATABASE')):
                    continue
                try:
                    cursor.execute(stmt)
                except pymysql.err.OperationalError as e:
                    if 'already exists' in str(e):
                        continue
                    raise

            self.conn.commit()
            cursor.close()
            logger.info("Schema initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Schema initialization error: {e}")
            self.conn.rollback()
            return False

    def execute_query(self, query: str, params: tuple = None) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            cursor.close()
            return True
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            self.conn.rollback()
            return False

    def insert_prices(self, records: List[Dict]) -> int:
        if not records:
            return 0

        try:
            cursor = self.conn.cursor()
            inserted = 0

            for record in records:
                try:
                    cursor.execute("""
                        INSERT INTO gold_prices
                        (symbol, price_date, price_datetime,
                         open_price, high_price, low_price, close_price,
                         volume, interval_type, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            open_price = VALUES(open_price),
                            high_price = VALUES(high_price),
                            low_price = VALUES(low_price),
                            close_price = VALUES(close_price),
                            volume = VALUES(volume)
                    """, (
                        record['symbol'],
                        record['date'],
                        record['datetime'],
                        record['open'],
                        record['high'],
                        record['low'],
                        record['close'],
                        record.get('volume', 0),
                        record.get('interval', '1d'),
                        'Yahoo Finance'
                    ))
                    inserted += 1
                except pymysql.err.IntegrityError:
                    pass

            self.conn.commit()
            logger.info(f"Inserted/updated {inserted} price records")
            cursor.close()
            return inserted

        except Exception as e:
            logger.error(f"Error inserting prices: {e}")
            self.conn.rollback()
            return 0

    def insert_signals(self, signals: List[Dict]) -> int:
        if not signals:
            return 0

        try:
            cursor = self.conn.cursor()
            inserted = 0

            for signal in signals:
                try:
                    cursor.execute("""
                        INSERT INTO technical_signals
                        (symbol, signal_date, signal_datetime,
                         signal_type, signal_value, signal_label, description)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            signal_value = VALUES(signal_value),
                            signal_label = VALUES(signal_label),
                            description = VALUES(description)
                    """, (
                        signal['symbol'],
                        signal['date'],
                        signal['datetime'],
                        signal['signal_type'],
                        signal.get('signal_value', 0),
                        signal['signal_label'],
                        signal.get('description', '')
                    ))
                    inserted += 1
                except pymysql.err.IntegrityError:
                    pass

            self.conn.commit()
            logger.info(f"Inserted/updated {inserted} signals")
            cursor.close()
            return inserted

        except Exception as e:
            logger.error(f"Error inserting signals: {e}")
            self.conn.rollback()
            return 0

    def insert_daily_summary(self, summary: Dict) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO daily_summary
                (symbol, summary_date, open_price, close_price, high_price, low_price,
                 price_change, price_change_pct, volume,
                 rsi_14, sma_20, sma_50, sma_200, ema_20,
                 macd_value, macd_signal, macd_histogram,
                 bb_upper, bb_middle, bb_lower, overall_signal)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    open_price = VALUES(open_price),
                    close_price = VALUES(close_price),
                    high_price = VALUES(high_price),
                    low_price = VALUES(low_price),
                    price_change = VALUES(price_change),
                    price_change_pct = VALUES(price_change_pct),
                    volume = VALUES(volume),
                    rsi_14 = VALUES(rsi_14),
                    sma_20 = VALUES(sma_20),
                    sma_50 = VALUES(sma_50),
                    sma_200 = VALUES(sma_200),
                    ema_20 = VALUES(ema_20),
                    macd_value = VALUES(macd_value),
                    macd_signal = VALUES(macd_signal),
                    macd_histogram = VALUES(macd_histogram),
                    bb_upper = VALUES(bb_upper),
                    bb_middle = VALUES(bb_middle),
                    bb_lower = VALUES(bb_lower),
                    overall_signal = VALUES(overall_signal)
            """, (
                summary['symbol'],
                summary['date'],
                summary.get('open'),
                summary.get('close'),
                summary.get('high'),
                summary.get('low'),
                summary.get('price_change'),
                summary.get('price_change_pct'),
                summary.get('volume', 0),
                summary.get('rsi_14'),
                summary.get('sma_20'),
                summary.get('sma_50'),
                summary.get('sma_200'),
                summary.get('ema_20'),
                summary.get('macd_value'),
                summary.get('macd_signal'),
                summary.get('macd_histogram'),
                summary.get('bb_upper'),
                summary.get('bb_middle'),
                summary.get('bb_lower'),
                summary.get('overall_signal', 'NEUTRAL'),
            ))

            self.conn.commit()
            cursor.close()
            logger.info(f"Saved daily summary for {summary['symbol']} {summary['date']}")
            return True

        except Exception as e:
            logger.error(f"Error saving daily summary: {e}")
            self.conn.rollback()
            return False

    def get_recent_prices(self, symbol: str = "GC=F",
                           days: int = 30, limit: int = 100) -> List[Dict]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM gold_prices
                WHERE symbol = %s
                  AND price_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY price_datetime DESC
                LIMIT %s
            """, (symbol, days, limit))

            results = cursor.fetchall()
            cursor.close()
            return results
        except Exception as e:
            logger.error(f"Error fetching recent prices: {e}")
            return []

    def get_all_prices(self, symbol: str = "GC=F",
                       limit: int = 1000) -> List[Dict]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM gold_prices
                WHERE symbol = %s
                ORDER BY price_datetime DESC
                LIMIT %s
            """, (symbol, limit))

            results = cursor.fetchall()
            cursor.close()
            return results
        except Exception as e:
            logger.error(f"Error fetching all prices: {e}")
            return []

    def get_price_stats(self, symbol: str = "GC=F",
                         days: int = None) -> Dict:
        try:
            cursor = self.conn.cursor()

            if days:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_records,
                        AVG(close_price) as avg_close,
                        MIN(low_price) as min_low,
                        MAX(high_price) as max_high,
                        AVG(volume) as avg_volume,
                        MIN(price_date) as first_date,
                        MAX(price_date) as last_date
                    FROM gold_prices
                    WHERE symbol = %s
                      AND price_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                """, (symbol, days))
            else:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total_records,
                        AVG(close_price) as avg_close,
                        MIN(low_price) as min_low,
                        MAX(high_price) as max_high,
                        AVG(volume) as avg_volume,
                        MIN(price_date) as first_date,
                        MAX(price_date) as last_date
                    FROM gold_prices
                    WHERE symbol = %s
                """, (symbol,))

            result = cursor.fetchone()
            cursor.close()

            if result:
                return {
                    'total_records': result['total_records'],
                    'avg_close': float(result['avg_close'] or 0),
                    'min_low': float(result['min_low'] or 0),
                    'max_high': float(result['max_high'] or 0),
                    'avg_volume': float(result['avg_volume'] or 0),
                    'first_date': str(result['first_date'] or ''),
                    'last_date': str(result['last_date'] or ''),
                }
            return {}

        except Exception as e:
            logger.error(f"Error fetching price stats: {e}")
            return {}

    def get_signal_stats(self, symbol: str = "GC=F",
                         days: int = None) -> Dict:
        try:
            cursor = self.conn.cursor()

            if days:
                cursor.execute("""
                    SELECT
                        signal_label,
                        COUNT(*) as count,
                        AVG(signal_value) as avg_value
                    FROM technical_signals
                    WHERE symbol = %s
                      AND signal_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                    GROUP BY signal_label
                """, (symbol, days))
            else:
                cursor.execute("""
                    SELECT
                        signal_label,
                        COUNT(*) as count,
                        AVG(signal_value) as avg_value
                    FROM technical_signals
                    WHERE symbol = %s
                    GROUP BY signal_label
                """, (symbol,))

            results = cursor.fetchall()
            cursor.close()

            stats = {}
            for row in results:
                stats[row['signal_label']] = {
                    'count': row['count'],
                    'avg_value': float(row['avg_value'] or 0),
                }
            return stats

        except Exception as e:
            logger.error(f"Error fetching signal stats: {e}")
            return {}

    def get_daily_summaries(self, symbol: str = "GC=F",
                             days: int = 30) -> List[Dict]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM daily_summary
                WHERE symbol = %s
                  AND summary_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                ORDER BY summary_date DESC
            """, (symbol, days))

            results = cursor.fetchall()
            cursor.close()
            return results
        except Exception as e:
            logger.error(f"Error fetching daily summaries: {e}")
            return []

    def get_latest_signals(self, symbol: str = "GC=F",
                           limit: int = 20) -> List[Dict]:
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM technical_signals
                WHERE symbol = %s
                ORDER BY signal_datetime DESC
                LIMIT %s
            """, (symbol, limit))

            results = cursor.fetchall()
            cursor.close()
            return results
        except Exception as e:
            logger.error(f"Error fetching latest signals: {e}")
            return []

    def get_record_count(self) -> int:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM gold_prices")
            result = cursor.fetchone()
            cursor.close()
            return result['cnt']
        except Exception:
            return 0


if __name__ == "__main__":
    print("Testing MySQL Database Module")

    try:
        db = DatabaseMySQL()
        db.init_schema()

        sample = [{
            'symbol': 'GC=F',
            'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'date': datetime.now().strftime('%Y-%m-%d'),
            'open': 2045.50,
            'high': 2060.00,
            'low': 2040.00,
            'close': 2055.75,
            'volume': 150000,
            'interval': '1d',
        }]

        inserted = db.insert_prices(sample)
        print(f"Inserted: {inserted} price records")

        stats = db.get_price_stats('GC=F')
        print(f"Price stats: {stats}")

        count = db.get_record_count()
        print(f"Total records: {count}")

        db.close()
        print("MySQL module test complete.")

    except Exception as e:
        print(f"Error: {e}")
