"""
FRED (Federal Reserve Economic Data) fetcher — direct download from the
public CSV endpoint, no API key or `fredapi` dependency needed.

SOURCES & OFFICIAL REFERENCES:
- https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID> (confirmed
  during the feasibility survey to work with no auth for every series this
  project uses)

Series used by this project:
- DFF: true DAILY Federal Funds Rate (published every day including
  weekends, flat between FOMC moves). NOT FEDFUNDS -- that series is a
  MONTHLY average and would silently misrepresent "daily" granularity if
  used here; confirmed the difference during the feasibility survey.
- DFII10: 10-Year Treasury Inflation-Indexed (TIPS) real yield, daily
  (business days). The single most commonly cited macro driver of gold in
  the literature -- more so than nominal yields, since gold has no yield
  of its own and its opportunity cost is the REAL rate, not the nominal one.
- CPIAUCSL: CPI, all urban consumers, seasonally adjusted -- MONTHLY, not
  daily like the other two. Granularity mismatch is handled downstream via
  the same merge_asof(direction="backward") forward-fill pattern already
  used for COT's weekly reports onto daily price (see
  run_intermarket_divergence_detection.py) -- one CPI reading holds until
  the next one, not interpolated. Persisted as the raw index level
  (cpi_index), not a pre-computed inflation rate -- keeping the raw layer
  a pure mirror of the source, same convention as every other raw table.

One generic fetch function handles all three (and any future FRED series)
since every series shares the same two-column CSV shape
(observation_date,<SERIES_ID>) -- only the persisted value's column name
and target table differ, handled by the caller (see
scripts/sync/sync_fred_data.py), not by this module.
"""

import logging
from io import StringIO
from typing import Dict, List

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# series_id -> the DB column name this project persists it under.
FRED_SERIES = {
    "DFF": "rate_pct",
    "DFII10": "real_yield_pct",
    "CPIAUCSL": "cpi_index",
}


class FredFetcher:
    """Fetches a daily FRED series from the public fredgraph.csv endpoint."""

    def __init__(self):
        logger.info("FRED fetcher initialized")

    def fetch_series(self, series_id: str) -> List[Dict]:
        if series_id not in FRED_SERIES:
            raise ValueError(f"Unknown FRED series {series_id!r}. Supported: {sorted(FRED_SERIES)}")

        url = FRED_CSV_URL.format(series_id=series_id)
        try:
            # No custom User-Agent -- fred.stlouisfed.org resets the
            # connection on the generic "Mozilla/5.0" string other
            # fetchers in this project use (confirmed by isolating it:
            # requests' own default UA succeeds in ~1.5s, "Mozilla/5.0"
            # times out/resets every time). Leave the header off entirely
            # rather than guess a different fake one.
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"FRED fetch failed for {series_id}: {e}")
            return []

        try:
            df = pd.read_csv(StringIO(resp.text))
        except Exception as e:
            logger.error(f"FRED CSV parse failed for {series_id}: {e}")
            return []

        value_col = FRED_SERIES[series_id]
        records = parse_fred_dataframe(df, series_id, value_col)
        logger.info(f"Fetched {len(records)} {series_id} records")
        return records


def parse_fred_dataframe(df: pd.DataFrame, series_id: str, value_col: str) -> List[Dict]:
    """
    Column-mapping/type-coercion logic split out from fetch_series() so it
    can be unit-tested against a small in-memory DataFrame without a real
    network call -- see tests/test_fred_fetcher.py. FRED occasionally marks
    a missing observation with "." (e.g. a data revision gap) rather than
    omitting the row -- pd.to_numeric(errors="coerce") + dropna handles
    that the same way gpr_fetcher.py handles unparseable values.
    """
    df = df.rename(columns={"observation_date": "report_date", series_id: "value"})
    df["report_date"] = pd.to_datetime(df["report_date"], errors="coerce").dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["report_date", "value"])
    df = df.sort_values("report_date").drop_duplicates(subset=["report_date"])

    return [
        {"report_date": r["report_date"], value_col: r["value"]}
        for r in df[["report_date", "value"]].to_dict("records")
    ]


if __name__ == "__main__":
    print("FRED Fetcher Test (Fed Funds Rate + 10Y TIPS real yield)")

    client = FredFetcher()
    for series_id in FRED_SERIES:
        records = client.fetch_series(series_id)
        print(f"\n{series_id}: {len(records)} records")
        if records:
            print(f"  first: {records[0]}")
            print(f"  last:  {records[-1]}")
