"""
Geopolitical Risk Index (GPR) fetcher — Caldara & Iacoviello's daily index,
published by the Federal Reserve, direct download from matteoiacoviello.com.

SOURCES & OFFICIAL REFERENCES:
- https://www.matteoiacoviello.com/gpr.htm (project home, methodology)
- https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls (the
  file this fetcher pulls: daily index, most recent ~40 years, updated
  same-day)

The source file is a legacy .xls (not .xlsx) -- pandas needs the `xlrd`
package to read it (openpyxl, already a project dependency, only handles
.xlsx). Confirmed real and current during the feasibility survey: fetching
it returned a `Last-Modified` header dated the same day as the check.

Only the headline index and its two published sub-components/moving
averages are persisted (gprd, gprd_act, gprd_threat, gprd_ma7, gprd_ma30)
-- the source file's other columns (N10D, event, var_name, var_label) are
either redundant with gprd or sparse one-off annotation fields, not part
of the daily numeric series this project's divergence engine consumes.
"""

import logging
from io import BytesIO
from typing import Dict, List

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GPR_DAILY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"

_PERSISTED_COLS = ["gprd", "gprd_act", "gprd_threat", "gprd_ma7", "gprd_ma30"]


class GprFetcher:
    """Fetches the daily Geopolitical Risk Index from matteoiacoviello.com."""

    def __init__(self):
        logger.info("GPR fetcher initialized")

    def fetch_history(self) -> List[Dict]:
        try:
            resp = requests.get(GPR_DAILY_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"GPR fetch failed: {e}")
            return []

        try:
            df = pd.read_excel(BytesIO(resp.content))
        except Exception as e:
            logger.error(f"GPR xls parse failed: {e}")
            return []

        records = parse_gpr_dataframe(df)
        logger.info(f"Fetched {len(records)} GPR daily records")
        return records


def parse_gpr_dataframe(df: pd.DataFrame) -> List[Dict]:
    """
    Column-mapping/type-coercion logic split out from fetch_history() so it
    can be unit-tested against a small in-memory DataFrame (matching the
    source's real column names/shapes) without needing network access or a
    real .xls binary -- see tests/test_gpr_fetcher.py.
    """
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    df = df.rename(columns={"date": "report_date"})
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.date
    df = df.dropna(subset=["report_date"])
    for col in _PERSISTED_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.sort_values("report_date").drop_duplicates(subset=["report_date"])

    return df[["report_date"] + _PERSISTED_COLS].to_dict("records")


if __name__ == "__main__":
    print("GPR Fetcher Test (Geopolitical Risk Index, daily)")

    client = GprFetcher()
    records = client.fetch_history()
    print(f"\n{len(records)} records")
    if records:
        print(f"  first: {records[0]}")
        print(f"  last:  {records[-1]}")
