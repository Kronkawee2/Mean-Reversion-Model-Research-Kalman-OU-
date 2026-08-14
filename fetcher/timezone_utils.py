"""
Shared timestamp-normalization helper for Yahoo Finance-sourced data.

yfinance's returned DataFrame index is tz-aware, localized to the source
exchange's own timezone (e.g. America/New_York for GC=F/DX-Y.NYB/GDX,
Europe/London for EURUSD=X, America/Chicago for ^TNX/^VIX) — NOT UTC.
Every Yahoo-sourced fetcher in this project at the time (yahoo_finance_client.py,
market_fetcher.py, and the now-removed sync_step1.py) previously stripped tzinfo without first
converting to UTC (`.tz_localize(None)` or a bare `.strftime()` on the
tz-aware index), silently writing exchange-local wall-clock time into the
DB labeled as if it were UTC. Found via a real-data cross-check against a
true-UTC reference (the same method used to find and fix the sibling MT5
broker-offset bug in mt5_data_fetcher.py). Offsets vary by exchange AND by
each exchange's own DST calendar (observed: -4h for NY-timezone tickers in
EDT, +1h for London in BST, -5h for Chicago in CDT — all shift by another
hour outside DST) — this can never be a hardcoded constant, it must always
be derived from the timestamp's own tzinfo.
"""

import pandas as pd


def to_utc_naive(ts: pd.Timestamp) -> pd.Timestamp:
    """
    Converts a yfinance-returned (tz-aware, exchange-local) timestamp to a
    naive UTC pd.Timestamp. Naive because this project's MySQL DATETIME
    columns are naive and every other fetcher stores UTC wall-clock numbers
    without a tzinfo suffix by convention. A timestamp that's already naive
    is returned unchanged (yfinance intraday/daily data is normally
    tz-aware, but this avoids raising on an unexpected edge case rather
    than silently mislabeling it further).
    """
    if ts.tzinfo is None:
        return ts
    return ts.tz_convert("UTC").tz_localize(None)
