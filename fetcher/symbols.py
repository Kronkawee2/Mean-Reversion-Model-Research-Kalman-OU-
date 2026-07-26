"""
Gold symbols list and helper functions for Yahoo Finance.
"""

GOLD_SYMBOLS = [
    ("XAUUSD=X", "Gold/USD Spot", "spot"),
    ("EURUSD=X", "EUR/USD Forex Spot", "forex"),
    ("GC=F", "Gold Futures", "futures"),
    ("GLD", "SPDR Gold Shares ETF", "etf"),
    ("IAU", "iShares Gold Trust ETF", "etf"),
    ("SI=F", "Silver Futures", "futures"),
    ("DX-Y.NYB", "US Dollar Index", "index"),
]

DEFAULT_SYMBOL = "GC=F"
DAILY_SYMBOLS = ["GC=F", "EURUSD=X"]

VALID_INTERVALS = [
    "1m", "2m", "5m", "15m", "30m", "60m", "90m",
    "1h", "1d", "5d", "1wk", "1mo", "3mo"
]

VALID_PERIODS = [
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y",
    "5y", "10y", "ytd", "max"
]


def get_symbol_info(symbol: str) -> dict:
    for sym, desc, cat in GOLD_SYMBOLS:
        if sym == symbol:
            return {"symbol": sym, "description": desc, "category": cat}
    return {"symbol": symbol, "description": "Unknown", "category": "unknown"}


def get_symbols_by_category(category: str) -> list:
    return [sym for sym, _, cat in GOLD_SYMBOLS if cat == category]


if __name__ == "__main__":
    print("Gold Yahoo Finance Symbols")
    for sym, desc, cat in GOLD_SYMBOLS:
        print(f"  {sym:15s}  {desc:30s}  [{cat}]")
    print(f"\nDefault: {DEFAULT_SYMBOL}")
    print(f"Daily:   {DAILY_SYMBOLS}")
