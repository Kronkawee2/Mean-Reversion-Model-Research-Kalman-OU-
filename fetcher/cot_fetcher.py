"""
CFTC Commitment of Traders (COT) fetcher — Legacy report, gold + EUR.

SOURCES & OFFICIAL REFERENCES:
- CFTC Commitment of Traders Reports: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
- cot_reports package: https://pypi.org/project/cot-reports/

Uses the `cot_reports` package as specified in the original plan — it
downloads directly from cftc.gov's own zip archives, so this is the
official source, just fetched through a maintained wrapper instead of
hand-rolling zip/txt parsing.

Report type: Legacy ("legacy_fut"), not Disaggregated or Traders in
Financial Futures (TFF). Gold futures are categorized under the
Disaggregated report and EUR futures under TFF — those two report types
have genuinely different category schemas (Producer/Merchant/Swap
Dealer/Managed Money for physical commodities vs Dealer/Asset
Manager/Leveraged Money for financial futures), so unifying gold and EUR
into one table would mean reconciling two different schemas. The Legacy
report's Commercial/Non-Commercial split is available for both markets
with one uniform schema, has the deepest history (gold back to 1986, EUR
back to 2000), and matches what most public COT charts/trackers default
to display — confirmed with the user before building.

COT reports are weekly (Tuesday data, published Friday), not daily/
hourly like every other raw source in this project — the schema
(raw_cot.gold / raw_cot.eur) reflects that with `report_date` instead of
`price_datetime` and no OHLC columns, deliberately not forced into the
project's usual OHLCV table shape.
"""

import logging
from typing import Dict, List, Optional

import pandas as pd
import cot_reports as cot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# market -> exact CFTC "Market and Exchange Names" value in the Legacy report
COT_CONTRACT_NAMES = {
    "gold": "GOLD - COMMODITY EXCHANGE INC.",
    "eur": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
}

# cot_reports' legacy_fut report uses spaced column names (its other report
# types use underscore names instead) — a package inconsistency, not ours;
# mapped explicitly here rather than relying on it staying that way.
_COLUMN_MAP = {
    "As of Date in Form YYYY-MM-DD": "report_date",
    "Open Interest (All)": "open_interest_all",
    "Noncommercial Positions-Long (All)": "noncommercial_long",
    "Noncommercial Positions-Short (All)": "noncommercial_short",
    "Noncommercial Positions-Spreading (All)": "noncommercial_spreading",
    "Commercial Positions-Long (All)": "commercial_long",
    "Commercial Positions-Short (All)": "commercial_short",
    "Nonreportable Positions-Long (All)": "nonreportable_long",
    "Nonreportable Positions-Short (All)": "nonreportable_short",
}

# cot_hist() bulk-downloads history through this year; cot_year() is used
# per-year for everything after, since cot_hist() doesn't include the
# current, still-accumulating year's data.
HIST_END_YEAR = 2016


class CotFetcher:
    """Fetches CFTC Legacy COT report data (Commercial/Non-Commercial positioning) for gold and EUR futures."""

    def __init__(self):
        logger.info("COT fetcher initialized")

    def fetch_market_history(self, market: str, start_year: Optional[int] = None) -> List[Dict]:
        """
        Fetches the full available Legacy COT history for `market` ('gold'
        or 'eur'), from cot_hist() (1986-2016 bulk archive) plus a
        cot_year() call per year from 2017 through the current year.
        start_year, if given, filters the returned records (fetching itself
        still pulls full history — the bulk/yearly split is fixed by the
        package, not something to fetch partially).
        """
        if market not in COT_CONTRACT_NAMES:
            raise ValueError(f"Unknown COT market {market!r}. Supported: {sorted(COT_CONTRACT_NAMES)}")
        contract_name = COT_CONTRACT_NAMES[market]

        frames = []
        try:
            hist_df = cot.cot_hist(cot_report_type="legacy_fut", store_txt=False, verbose=False)
            frames.append(hist_df)
        except Exception as e:
            logger.error(f"COT bulk history fetch failed: {e}")

        current_year = pd.Timestamp.now().year
        for year in range(HIST_END_YEAR + 1, current_year + 1):
            try:
                year_df = cot.cot_year(year=year, cot_report_type="legacy_fut", store_txt=False, verbose=False)
                frames.append(year_df)
            except Exception as e:
                logger.warning(f"COT {year} fetch failed: {e}")

        if not frames:
            logger.error("No COT data fetched at all (bulk history and all yearly fetches failed)")
            return []

        combined = pd.concat(frames, ignore_index=True)
        combined = combined[combined["Market and Exchange Names"] == contract_name].copy()
        if combined.empty:
            logger.warning(f"No rows found for contract {contract_name!r}")
            return []

        combined = combined.rename(columns=_COLUMN_MAP)
        combined["report_date"] = pd.to_datetime(combined["report_date"]).dt.date
        combined = combined.drop_duplicates(subset=["report_date"]).sort_values("report_date")

        if start_year is not None:
            combined = combined[combined["report_date"].apply(lambda d: d.year) >= start_year]

        records = []
        for _, row in combined.iterrows():
            comm_long = int(row["commercial_long"])
            comm_short = int(row["commercial_short"])
            noncomm_long = int(row["noncommercial_long"])
            noncomm_short = int(row["noncommercial_short"])
            records.append({
                "report_date": row["report_date"],
                "open_interest_all": int(row["open_interest_all"]),
                "noncommercial_long": noncomm_long,
                "noncommercial_short": noncomm_short,
                "noncommercial_spreading": int(row["noncommercial_spreading"]),
                "commercial_long": comm_long,
                "commercial_short": comm_short,
                "nonreportable_long": int(row["nonreportable_long"]),
                "nonreportable_short": int(row["nonreportable_short"]),
                "commercial_net_position": comm_long - comm_short,
                "noncommercial_net_position": noncomm_long - noncomm_short,
            })

        logger.info(f"Fetched {len(records)} COT records for {market} ({contract_name})")
        return records


if __name__ == "__main__":
    print("COT Fetcher Test (Legacy report: gold + EUR)")

    client = CotFetcher()
    for market in ("gold", "eur"):
        records = client.fetch_market_history(market)
        print(f"\n{market}: {len(records)} records")
        if records:
            print(f"  first: {records[0]}")
            print(f"  last:  {records[-1]}")
