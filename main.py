"""
Main orchestrator for Gold Yahoo Finance Pipeline.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Gold Yahoo Finance Pipeline Started")

    try:
        from fetcher.yahoo_finance_client import YahooFinanceClient
        from analysis.technical_analysis import TechnicalAnalyzer
        from storage.database_mysql import DatabaseMySQL
        from fetcher.symbols import DAILY_SYMBOLS

        logger.info("Initializing pipeline components...")

        client = YahooFinanceClient()
        analyzer = TechnicalAnalyzer()
        db = DatabaseMySQL()

        db.init_schema()

        for symbol in DAILY_SYMBOLS:
            logger.info(f"Processing symbol: {symbol}")

            price_records = client.fetch_gold_data(symbol, period="5d", interval="1d")
            if not price_records:
                logger.warning(f"No data found for {symbol}")
                continue

            inserted = db.insert_prices(price_records)
            logger.info(f"Stored {len(price_records)} price records (inserted/updated: {inserted})")

            df = client.fetch_history(symbol, period="1y", interval="1d")
            if df.empty:
                logger.warning("Not enough historical data for analysis")
                continue

            result = analyzer.analyze(df)

            logger.info(f"{symbol} analysis - Signal: {result['signal']}")
            logger.info(f"Close: ${result['close']:.2f} (Change: ${result['price_change']:.2f}, {result['price_change_pct']:.2f}%)")

            for signal in result['signals']:
                logger.info(f"  {signal['type']:10s}: {signal['description']}")

            signal_records = analyzer.generate_signal_records(symbol, result)
            db.insert_signals(signal_records)

            daily_summary = analyzer.generate_daily_summary(symbol, df, result)
            db.insert_daily_summary(daily_summary)

        logger.info("Pipeline Statistics:")
        logger.info(f"Total price records: {db.get_record_count()}")

        for symbol in DAILY_SYMBOLS:
            stats = db.get_price_stats(symbol, days=7)
            if stats and stats.get('total_records', 0) > 0:
                logger.info(f"  {symbol}: avg=${stats['avg_close']:.2f}, range=${stats['min_low']:.2f}-${stats['max_high']:.2f}")

        logger.info("Pipeline completed successfully.")
        db.close()

    except ImportError as e:
        logger.error("Import error - ensure all dependencies are installed:")
        logger.error("pip install -r requirements.txt")
        logger.error(f"Error: {e}")

    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
