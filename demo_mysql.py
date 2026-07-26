"""
Demo script that fetches gold data from Yahoo Finance and stores it in MySQL database.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    print("Gold Yahoo Finance Tracker - Demo")
    print()

    try:
        from storage.database_mysql import DatabaseMySQL
        db = DatabaseMySQL()
        db.init_schema()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Error connecting to MySQL: {e}")
        print("Please check if MySQL server is running and .env configuration is correct.")
        return
    print()

    from fetcher.yahoo_finance_client import YahooFinanceClient
    from fetcher.symbols import DAILY_SYMBOLS

    client = YahooFinanceClient()
    all_records = []
    
    for symbol in DAILY_SYMBOLS:
        records = client.fetch_gold_data(symbol, period="1mo", interval="1d")
        all_records.extend(records)
        print(f"{symbol}: {len(records)} records fetched")

    print(f"Total records fetched: {len(all_records)}")
    print()

    inserted = db.insert_prices(all_records)
    print(f"Saved {inserted} price records to MySQL")
    print()

    from analysis.technical_analysis import TechnicalAnalyzer
    analyzer = TechnicalAnalyzer()

    for symbol in DAILY_SYMBOLS:
        df = client.fetch_history(symbol, period="1y", interval="1d")
        if df.empty:
            print(f"No history data for {symbol}")
            continue

        result = analyzer.analyze(df)

        signal_str = result['signal']
        print(f"{symbol} - Signal: {signal_str}")
        print(f"Close: ${result['close']:.2f} (Change: ${result['price_change']:.2f}, {result['price_change_pct']:.2f}%)")

        print("Indicators:")
        ind = result['indicators']
        print(f"  RSI(14)={ind['rsi_14']:.1f}  SMA20=${ind['sma_20']:.2f}  SMA50=${ind['sma_50']:.2f}")
        print(f"  MACD={ind['macd_value']:.4f}  Signal={ind['macd_signal']:.4f}  Hist={ind['macd_histogram']:.4f}")
        print(f"  BB: ${ind['bb_lower']:.2f} - ${ind['bb_middle']:.2f} - ${ind['bb_upper']:.2f}")

        print("Signals:")
        for sig in result['signals']:
            print(f"  {sig['type']:10s} {sig['label']:8s}  {sig['description']}")

        signal_records = analyzer.generate_signal_records(symbol, result)
        db.insert_signals(signal_records)

        daily_summary = analyzer.generate_daily_summary(symbol, df, result)
        db.insert_daily_summary(daily_summary)
        print()

    print("Database Stats Summary:")
    for symbol in DAILY_SYMBOLS:
        stats = db.get_price_stats(symbol)
        if stats and stats.get('total_records', 0) > 0:
            print(f"  {symbol}:")
            print(f"    Records: {stats['total_records']}")
            print(f"    Avg Close: ${stats['avg_close']:.2f}")
            print(f"    Range: ${stats['min_low']:.2f} - ${stats['max_high']:.2f}")
            print(f"    Period: {stats['first_date']} -> {stats['last_date']}")
            print()

    total = db.get_record_count()
    print(f"Demo complete. Total records in database: {total}")
    db.close()


if __name__ == "__main__":
    main()
