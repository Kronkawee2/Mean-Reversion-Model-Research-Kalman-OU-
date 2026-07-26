FROM apache/airflow:2.8.1-python3.11

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    default-libmysqlclient-dev \
    build-essential \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY fetcher/ /opt/airflow/fetcher/
COPY analysis/ /opt/airflow/analysis/
COPY storage/ /opt/airflow/storage/
COPY airflow/dags/ /opt/airflow/dags/

WORKDIR /opt/airflow
