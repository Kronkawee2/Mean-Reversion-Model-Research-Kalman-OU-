"""
Airflow DAG for automated daily sync of Quant Multi-Timeframe raw (Step 1) data.
Syncs raw_gold, raw_eurusd, raw_dxy, raw_us10y, raw_vix, raw_gdx into MySQL.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import logging
import sys

sys.path.insert(0, '/opt/airflow')

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'quant_trader',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}


def sync_quant_bronze_data(**context):
    from scripts.sync.quant_backend import QuantBackend

    logger.info("Starting Quant Bronze Multi-Timeframe sync...")
    backend = QuantBackend()
    try:
        results = backend.sync_all()
        logger.info(f"Sync complete: {results}")
    finally:
        backend.close()


with DAG(
    'quant_daily_sync',
    default_args=default_args,
    description='Automated daily sync for Quant Multi-Timeframe Bronze data',
    schedule_interval='0 18 * * *',
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=['quant', 'bronze', 'multi_tf'],
) as dag:

    task_sync = PythonOperator(
        task_id='sync_quant_bronze_data',
        python_callable=sync_quant_bronze_data,
    )
