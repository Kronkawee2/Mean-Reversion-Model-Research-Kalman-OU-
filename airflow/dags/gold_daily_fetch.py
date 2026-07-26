"""
Airflow DAG for fetching gold daily data from Yahoo Finance and analyzing indicators.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import logging
import sys

sys.path.insert(0, '/opt/airflow')

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'gold_tracker',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}


def fetch_gold_data(**context):
    from fetcher.yahoo_finance_client import YahooFinanceClient
    from fetcher.symbols import DAILY_SYMBOLS

    logger.info("Starting Yahoo Finance data fetch...")

    client = YahooFinanceClient()
    all_records = {}

    for symbol in DAILY_SYMBOLS:
        records = client.fetch_gold_data(symbol, period="5d", interval="1d")
        all_records[symbol] = records
        logger.info(f"  {symbol}: {len(records)} records")

    context['ti'].xcom_push(key='price_records', value=all_records)
    logger.info(f"Fetched data for {len(DAILY_SYMBOLS)} symbols")


def analyze_signals(**context):
    from fetcher.yahoo_finance_client import YahooFinanceClient
    from fetcher.symbols import DAILY_SYMBOLS
    from analysis.technical_analysis import TechnicalAnalyzer

    logger.info("Starting technical analysis...")

    client = YahooFinanceClient()
    analyzer = TechnicalAnalyzer()
    all_analysis = {}

    for symbol in DAILY_SYMBOLS:
        df = client.fetch_history(symbol, period="1y", interval="1d")
        if df.empty:
            logger.warning(f"No data for {symbol}")
            continue

        result = analyzer.analyze(df)
        all_analysis[symbol] = {
            'signal': result['signal'],
            'close': result['close'],
            'price_change': result['price_change'],
            'price_change_pct': result['price_change_pct'],
            'indicators': result['indicators'],
            'signals': result['signals'],
            'bullish_count': result['bullish_count'],
            'bearish_count': result['bearish_count'],
        }

        logger.info(f"  {symbol}: {result['signal']} (Close: ${result['close']:.2f}, Change: {result['price_change_pct']:.2f}%)")

    context['ti'].xcom_push(key='analysis_results', value=all_analysis)
    logger.info(f"Analysis complete for {len(all_analysis)} symbols")


def store_to_mysql(**context):
    from storage.database_mysql import DatabaseMySQL
    from fetcher.yahoo_finance_client import YahooFinanceClient
    from fetcher.symbols import DAILY_SYMBOLS
    from analysis.technical_analysis import TechnicalAnalyzer

    logger.info("Starting MySQL storage...")

    db = DatabaseMySQL()
    db.init_schema()

    price_records = context['ti'].xcom_pull(key='price_records', task_ids='fetch_gold_data')
    analysis_results = context['ti'].xcom_pull(key='analysis_results', task_ids='analyze_signals')

    total_inserted = 0
    if price_records:
        for symbol, records in price_records.items():
            inserted = db.insert_prices(records)
            total_inserted += inserted
            logger.info(f"  {symbol}: {inserted} price records stored")

    client = YahooFinanceClient()
    analyzer = TechnicalAnalyzer()

    for symbol in DAILY_SYMBOLS:
        if analysis_results and symbol in analysis_results:
            result = analysis_results[symbol]

            signal_records = analyzer.generate_signal_records(symbol, result)
            db.insert_signals(signal_records)

            df = client.fetch_history(symbol, period="1y", interval="1d")
            if not df.empty:
                daily_summary = analyzer.generate_daily_summary(symbol, df, result)
                db.insert_daily_summary(daily_summary)

            logger.info(f"  {symbol}: signals + summary stored")

    db.close()
    logger.info(f"Total: {total_inserted} price records stored to MySQL")


with DAG(
    'gold_daily_fetch',
    default_args=default_args,
    description='Fetch daily gold prices and calculate signals in MySQL',
    schedule_interval='0 18 * * *',
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=['gold', 'yahoo_finance', 'daily'],
) as dag:

    task_fetch = PythonOperator(
        task_id='fetch_gold_data',
        python_callable=fetch_gold_data,
    )

    task_analyze = PythonOperator(
        task_id='analyze_signals',
        python_callable=analyze_signals,
    )

    task_store = PythonOperator(
        task_id='store_to_mysql',
        python_callable=store_to_mysql,
    )

    task_fetch >> task_analyze >> task_store
