"""
SPDR Gold Shares (GLD) daily holdings fetcher — direct download from
SPDR's official site.

SOURCES & OFFICIAL REFERENCES:
- SPDR Gold Shares official historical data: https://www.spdrgoldshares.com/usa/historical-data/

The original plan specified a "direct CSV download," but SPDR's site has
since moved to an .xlsx endpoint (confirmed by fetching the live
historical-data page and finding its actual download link — the plan's
presumed CSV URL now 404s/redirects to an unrelated PDF, the HSBC gold
bar list). This fetcher uses the real current endpoint,
api.spdrgoldshares.com/api/v1/historical-archive, and parses the .xlsx it
returns.

GLD publishes ~200 "US Holiday" placeholder rows (every column literally
contains the string "US Holiday" instead of data) for market-closed days
— these are dropped rather than persisted as garbage rows.

Data is daily (unlike COT's weekly cadence) and goes back to GLD's
2004-11-18 inception.
"""

import logging
from io import BytesIO
from typing import Dict, List

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SPDR_HISTORICAL_ARCHIVE_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en"
SPDR_SHEET_NAME = "US GLD Historical Archive"

_COLUMN_MAP = {
    "Date": "report_date",
    "Closing Price": "closing_price",
    "Ounces of Gold per Share": "ounces_per_share",
    "NAV/Share at 10:30am NYT": "nav_per_share_1030",
    "Indicative Price per Share at 4:15pm NYT": "indicative_price_415",
    "Mid point of bid/ask spread at 4:15pm NYT": "bid_ask_midpoint_415",
    "Premium/Discount of GLD Mid Point vs Indicative Value of GLD at 4:15pm NYT": "premium_discount_pct",
    "Daily Share Volume": "daily_share_volume",
    "Total Ounces of Gold in the Trust": "total_ounces_in_trust",
    "Tonnes of Gold": "tonnes_of_gold",
    "Total Net Asset Value in the Trust": "total_nav",
}

_NUMERIC_COLS = [
    "closing_price", "ounces_per_share", "nav_per_share_1030", "indicative_price_415",
    "bid_ask_midpoint_415", "premium_discount_pct", "daily_share_volume",
    "total_ounces_in_trust", "tonnes_of_gold", "total_nav",
]


class SpdrFetcher:
    """Fetches SPDR Gold Shares (GLD) daily holdings data from spdrgoldshares.com."""

    def __init__(self):
        logger.info("SPDR fetcher initialized")

    def fetch_history(self) -> List[Dict]:
        try:
            resp = requests.get(SPDR_HISTORICAL_ARCHIVE_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"SPDR fetch failed: {e}")
            return []

        try:
            df = pd.read_excel(BytesIO(resp.content), sheet_name=SPDR_SHEET_NAME)
        except Exception as e:
            logger.error(f"SPDR xlsx parse failed: {e}")
            return []

        df = df.rename(columns=_COLUMN_MAP)
        before = len(df)
        df = df[df["closing_price"] != "US Holiday"].copy()
        dropped = before - len(df)
        if dropped:
            logger.info(f"Dropped {dropped} 'US Holiday' placeholder rows")

        df["report_date"] = pd.to_datetime(df["report_date"], format="%d-%b-%Y", errors="coerce").dt.date
        df = df.dropna(subset=["report_date"])
        for col in _NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values("report_date").drop_duplicates(subset=["report_date"])

        records = df[["report_date"] + _NUMERIC_COLS].to_dict("records")
        logger.info(f"Fetched {len(records)} SPDR GLD holdings records")
        return records


if __name__ == "__main__":
    print("SPDR Fetcher Test (GLD daily holdings)")

    client = SpdrFetcher()
    records = client.fetch_history()
    print(f"\n{len(records)} records")
    if records:
        print(f"  first: {records[0]}")
        print(f"  last:  {records[-1]}")
