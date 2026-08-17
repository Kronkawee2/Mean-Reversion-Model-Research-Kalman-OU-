"""
Yahoo Finance client for fetching macro market data. As of the Silver/DXY/
VIX MT5-migration decision (see docs/DECISIONS.md), this is now scoped to
US10Y and GDX only -- DXY, VIX, and SILVER moved to MT5 (USDX/VIX/XAGUSD,
resampled from h1, same pattern as gold/eurusd's h4/h6/d1). US10Y (no
bond/yield instrument on Eightcap) and GDX (no gold-miner ETF on Eightcap)
have no MT5 equivalent and stay here permanently. Mirrors
yahoo_finance_client.py's conventions (connection handling, retry-free
try/except-and-log-empty behavior, logging style).
"""

import yfinance as yf
import logging
from typing import List, Dict, Optional
import pandas as pd

from fetcher.timezone_utils import to_utc_naive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# asset name -> (yfinance ticker, rounding decimals)
MACRO_SYMBOLS = {
    "US10Y":  ("^TNX", 3),
    "GDX":    ("GDX", 2),
}

# asset name -> supported timeframes (matches storage/schema_raw.sql)
MACRO_ASSET_TF = {
    "US10Y":  ["d1"],
    "GDX":    ["d1"],
}

TIMEFRAME_INTERVAL = {"h1": "1h", "d1": "1d"}


class MarketFetcher:
    """Client wrapper for yfinance API, scoped to macro assets (DXY/US10Y/VIX/GDX)."""

    def __init__(self):
        logger.info("Market fetcher initialized")

    def fetch_market_data(self, asset: str, timeframe: str,
                           period: Optional[str] = None) -> List[Dict]:
        if asset not in MACRO_SYMBOLS:
            raise ValueError(f"Unknown macro asset {asset!r}. Supported: {sorted(MACRO_SYMBOLS)}")
        if timeframe not in MACRO_ASSET_TF.get(asset, []):
            raise ValueError(f"{asset} does not support timeframe {timeframe!r}. "
                              f"Supported: {MACRO_ASSET_TF.get(asset, [])}")

        symbol, dec = MACRO_SYMBOLS[asset]
        interval = TIMEFRAME_INTERVAL[timeframe]
        period = period or ("730d" if interval == "1h" else "max")

        try:
            logger.info(f"Fetching {asset} ({symbol}) data (period={period}, interval={interval})")

            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"No data found for {asset} ({symbol})")
                return []

            records = []
            for index, row in df.iterrows():
                index_utc = to_utc_naive(index)
                records.append({
                    'symbol': asset,
                    'datetime': index_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    'date': index_utc.strftime('%Y-%m-%d'),
                    'open': round(float(row['Open']), dec),
                    'high': round(float(row['High']), dec),
                    'low': round(float(row['Low']), dec),
                    'close': round(float(row['Close']), dec),
                    'volume': int(row['Volume']) if pd.notna(row['Volume']) else 0,
                    'interval': interval,
                })

            logger.info(f"Fetched {len(records)} records for {asset}")
            return records

        except Exception as e:
            logger.error(f"Error fetching {asset} ({symbol}): {e}")
            return []

    def fetch_all_timeframes(self, asset: str) -> Dict[str, List[Dict]]:
        return {tf: self.fetch_market_data(asset, tf) for tf in MACRO_ASSET_TF.get(asset, [])}


if __name__ == "__main__":
    print("Market Fetcher Test (DXY/US10Y/VIX/GDX)")

    client = MarketFetcher()
    for asset in MACRO_SYMBOLS:
        for tf in MACRO_ASSET_TF[asset]:
            data = client.fetch_market_data(asset, tf, period="5d" if tf != "d1" else "5d")
            print(f"\n{asset} [{tf}] - last {len(data)} records")
            for record in data[-3:]:
                print(f"  {record['datetime']}  O:{record['open']:>10.3f}  "
                      f"H:{record['high']:>10.3f}  L:{record['low']:>10.3f}  "
                      f"C:{record['close']:>10.3f}")
