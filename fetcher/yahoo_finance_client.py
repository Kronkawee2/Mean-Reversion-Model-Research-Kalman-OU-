"""
Yahoo Finance client for fetching gold price data.
"""

import yfinance as yf
import logging
from typing import List, Dict, Optional
import pandas as pd

from fetcher.timezone_utils import to_utc_naive

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class YahooFinanceClient:
    """Client wrapper for yfinance API."""

    def __init__(self):
        logger.info("Yahoo Finance client initialized")

    def fetch_gold_data(self, symbol: str = "GC=F",
                        period: str = "5d",
                        interval: str = "1d",
                        decimals: int = 2,
                        reject_flat_ohlc: bool = False) -> List[Dict]:
        """
        decimals: rounding precision for OHLC values. Must match the
        instrument's real quote precision — hardcoding 2 for every symbol
        previously collapsed EUR/USD (needs 5) to cent-level values,
        producing dead-flat 1.15000/1.16000-style rows across 100% of
        raw_eurusd.h4/d1 history. Callers MUST pass the correct decimals for
        non-gold instruments; the default of 2 is gold-only.

        reject_flat_ohlc: if True, a row where open==high==low==close
        after rounding is dropped and logged rather than persisted. Only
        safe to enable for high-precision instruments (FX, decimals>=4)
        where a truly flat bar is not realistic market behavior; gold at
        2-decimal precision legitimately produces flat quiet-day bars
        (~12% of its d1 history), so this must stay off for gold.
        """
        try:
            logger.info(f"Fetching {symbol} data (period={period}, interval={interval})")

            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"No data found for {symbol}")
                return []

            records = []
            skipped_flat = 0
            for index, row in df.iterrows():
                index_utc = to_utc_naive(index)
                o = round(float(row['Open']), decimals)
                h = round(float(row['High']), decimals)
                l = round(float(row['Low']), decimals)
                c = round(float(row['Close']), decimals)

                if reject_flat_ohlc and o == h == l == c:
                    skipped_flat += 1
                    continue

                records.append({
                    'symbol': symbol,
                    'datetime': index_utc.strftime('%Y-%m-%d %H:%M:%S'),
                    'date': index_utc.strftime('%Y-%m-%d'),
                    'open': o,
                    'high': h,
                    'low': l,
                    'close': c,
                    'volume': int(row['Volume']) if pd.notna(row['Volume']) else 0,
                    'interval': interval,
                })

            if skipped_flat:
                logger.warning(f"Skipped {skipped_flat} suspected placeholder rows "
                                f"(flat OHLC at {decimals} decimals) for {symbol}")
            logger.info(f"Fetched {len(records)} records for {symbol}")
            return records

        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return []

    def fetch_multiple_symbols(self, symbols: List[str],
                                period: str = "5d",
                                interval: str = "1d") -> Dict[str, List[Dict]]:
        all_data = {}
        for symbol in symbols:
            all_data[symbol] = self.fetch_gold_data(symbol, period, interval)
        return all_data

    def fetch_history(self, symbol: str = "GC=F",
                      period: str = "1y",
                      interval: str = "1d") -> pd.DataFrame:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"No history data for {symbol}")
                return pd.DataFrame()

            logger.info(f"Fetched {len(df)} historical records for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Error fetching history for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_today(self, symbol: str = "GC=F") -> Optional[Dict]:
        data = self.fetch_gold_data(symbol, period="1d", interval="1d")
        return data[-1] if data else None

    def get_ticker_info(self, symbol: str = "GC=F") -> Dict:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return {
                'symbol': symbol,
                'name': info.get('shortName', info.get('longName', symbol)),
                'currency': info.get('currency', 'USD'),
                'exchange': info.get('exchange', 'Unknown'),
                'market_price': info.get('regularMarketPrice', 0),
                'previous_close': info.get('previousClose', 0),
                'day_high': info.get('dayHigh', 0),
                'day_low': info.get('dayLow', 0),
            }
        except Exception as e:
            logger.error(f"Error getting ticker info for {symbol}: {e}")
            return {'symbol': symbol, 'name': symbol}

    def fetch_daily_data(self, symbol: str = "GC=F",
                         days_back: int = 1) -> List[Dict]:
        period = f"{days_back}d" if days_back <= 5 else f"{days_back // 30 + 1}mo"
        return self.fetch_gold_data(symbol, period=period, interval="1d")


if __name__ == "__main__":
    print("Yahoo Finance Client Test")

    client = YahooFinanceClient()

    print("\nGold Futures (GC=F) - Last 5 days")
    data = client.fetch_gold_data("GC=F", period="5d", interval="1d")
    for record in data:
        print(f"  {record['date']}  O:{record['open']:>8.2f}  "
              f"H:{record['high']:>8.2f}  L:{record['low']:>8.2f}  "
              f"C:{record['close']:>8.2f}  V:{record['volume']:>10,}")

    print("\nToday's Gold Price")
    today = client.fetch_today("GC=F")
    if today:
        print(f"  Price: ${today['close']:.2f}")
        print(f"  Range: ${today['low']:.2f} - ${today['high']:.2f}")

    print("\nTicker Info")
    info = client.get_ticker_info("GC=F")
    for k, v in info.items():
        print(f"  {k}: {v}")
