"""
Standalone MT5 connection test. Run this first to validate the fetcher
against a live (or demo) Eightcap account before using mt5_data_fetcher.py.

Usage: python tests/test_mt5_connection.py
"""

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sync.mt5_data_fetcher import MT5DataFetcher, MT5SymbolError  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main():
    fetcher = MT5DataFetcher()
    try:
        print("Connecting to MT5...")
        account = fetcher.connect()
        print(f"OK: login={account.login} server={account.server} balance={account.balance}")

        candidates = ["XAUUSD", "XAUUSD.a", "XAUUSDm", "GOLD"]
        found = None
        for symbol in candidates:
            try:
                fetcher.check_symbol(symbol)
                print(f"OK: symbol {symbol} verified")
                found = symbol
                break
            except MT5SymbolError as e:
                print(f"  {symbol} not usable: {e}")

        if not found:
            print("No candidate gold symbol found. Gold-related symbols on this account:")
            print(fetcher.search_gold_symbols())
            sys.exit(1)

        tick = fetcher.get_latest_tick(found)
        print(f"OK: latest tick for {found}: bid={tick['bid']} ask={tick['ask']}")

        df = fetcher.get_latest_rates(found, "M5", count=5)
        print(f"OK: fetched {len(df)} latest closed M5 candles")
        print(df)

    finally:
        fetcher.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
