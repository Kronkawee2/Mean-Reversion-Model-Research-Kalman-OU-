"""
Database initialization script for Gold Yahoo Finance Tracker.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


def init_database():
    try:
        import pymysql
    except ImportError:
        logger.error("pymysql not installed. Run: pip install pymysql")
        return False

    try:
        schema_path = Path(__file__).parent / "storage" / "schema_mysql.sql"
        if not schema_path.exists():
            logger.error(f"Schema file not found: {schema_path}")
            return False

        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()

        host = os.getenv('DB_HOST', 'localhost')
        port = int(os.getenv('DB_PORT', 3306))
        user = os.getenv('DB_USER', 'root')
        password = os.getenv('DB_PASSWORD', '')
        database = os.getenv('DB_NAME', 'gold_yahoo_finance')

        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset='utf8mb4'
        )

        cursor = conn.cursor()
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        conn.commit()
        logger.info(f"Database '{database}' ready")

        conn.select_db(database)

        statements = [s.strip() for s in schema_sql.split(';') if s.strip()]
        for stmt in statements:
            if stmt.upper().startswith(('USE ', 'CREATE DATABASE')):
                continue
            try:
                cursor.execute(stmt)
            except pymysql.err.OperationalError as e:
                if 'already exists' in str(e):
                    continue
                logger.warning(f"Statement warning: {e}")

        conn.commit()

        logger.info("Schema initialized successfully")
        logger.info("Tables created: gold_symbols, gold_prices, technical_signals, daily_summary")

        cursor.close()
        conn.close()

        logger.info("Database initialization complete.")
        return True

    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return False


if __name__ == "__main__":
    import sys

    logger.info("Gold Yahoo Finance Tracker - Database Initialization")
    logger.info("")

    success = init_database()
    sys.exit(0 if success else 1)
