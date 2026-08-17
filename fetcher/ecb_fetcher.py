"""
ECB Data Portal fetcher — euro area 10-year AAA yield curve spot rate,
direct download via the ECB's public SDMX REST API (no API key needed).

SOURCES & OFFICIAL REFERENCES:
- https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y
  (confirmed during the feasibility survey to work with no auth, csvdata
  format, daily/business-day observations)

Series key: YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y = "AAA yield curve -
10-year spot rate" (euro area, changing composition, government bonds
rated AAA, Svensson model, spot rate). This is the DAILY series, not
ECB's other "long-term interest rate for convergence purposes" series
(IRS.M.U2...), which is monthly and would be the wrong choice for
matching US10Y's daily granularity (^TNX via Yahoo, see
fetcher/market_fetcher.py) -- confirmed the daily/monthly distinction
during the feasibility survey before picking this series.
"""

import logging
from io import StringIO
from typing import Dict, List

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ECB_SERIES_KEY = "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"
ECB_URL = f"https://data-api.ecb.europa.eu/service/data/{ECB_SERIES_KEY}?format=csvdata"


class EcbFetcher:
    """Fetches the daily euro area 10-year AAA yield curve spot rate from the ECB Data Portal."""

    def __init__(self):
        logger.info("ECB fetcher initialized")

    def fetch_series(self) -> List[Dict]:
        try:
            resp = requests.get(ECB_URL, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"ECB fetch failed: {e}")
            return []

        try:
            df = pd.read_csv(StringIO(resp.text))
        except Exception as e:
            logger.error(f"ECB CSV parse failed: {e}")
            return []

        records = parse_ecb_dataframe(df)
        logger.info(f"Fetched {len(records)} ECB EU10Y records")
        return records


def parse_ecb_dataframe(df: pd.DataFrame) -> List[Dict]:
    """
    Column-mapping/type-coercion logic split out from fetch_series() so it
    can be unit-tested against a small in-memory DataFrame without a real
    network call -- see tests/test_ecb_fetcher.py. The ECB's SDMX csvdata
    response carries ~30 metadata columns per row (KEY, FREQ, OBS_STATUS,
    TITLE_COMPL, ...); only TIME_PERIOD/OBS_VALUE are the actual series
    data, everything else is dropped rather than persisted.
    """
    df = df.rename(columns={"TIME_PERIOD": "report_date", "OBS_VALUE": "yield_pct"})
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.date
    df["yield_pct"] = pd.to_numeric(df["yield_pct"], errors="coerce")
    df = df.dropna(subset=["report_date", "yield_pct"])
    df = df.sort_values("report_date").drop_duplicates(subset=["report_date"])

    return df[["report_date", "yield_pct"]].to_dict("records")


if __name__ == "__main__":
    print("ECB Fetcher Test (Euro area 10Y AAA yield curve spot rate)")

    client = EcbFetcher()
    records = client.fetch_series()
    print(f"\n{len(records)} records")
    if records:
        print(f"  first: {records[0]}")
        print(f"  last:  {records[-1]}")
