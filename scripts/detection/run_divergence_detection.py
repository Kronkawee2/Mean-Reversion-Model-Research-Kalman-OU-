"""
Runs TechnicalDivergenceEngine against real synced h1 price + indicator
data (indicator read from curated_<symbol>.features) and upserts the
resulting Regular + Hidden Bullish/Bearish divergence signals into
curated_<symbol>.divergence_signals. Prints a summary + concrete examples
for manual/chart cross-checking, same pattern as the other run_*.py
scripts.

RSI (Phase 2e), OBV (Phase 2f), and Stochastic %K + CCI 20 (Phase 2g) all
wired up via --indicator, completing Category 2 (Technical) of the
divergence matrix; see
analysis/divergence/technical_divergence_state.py module docstring for
what's still deferred (inter-market, MTF alignment). Stochastic divergence
uses %K, not %D — %K is the more responsive line and the one commonly
read for divergence; %D is a smoothing/signal line normally reserved for
%K/%D crossover signals, not divergence.

Usage:
    python scripts/detection/run_divergence_detection.py --symbol XAUUSD --indicator rsi
    python scripts/detection/run_divergence_detection.py --symbol XAUUSD --indicator obv
    python scripts/detection/run_divergence_detection.py --symbol XAUUSD --indicator stochastic
    python scripts/detection/run_divergence_detection.py --symbol XAUUSD --indicator cci
    python scripts/detection/run_divergence_detection.py --symbol EURUSD --indicator obv --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.divergence.technical_divergence_state import TechnicalDivergenceEngine  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}

# divergence_type -> features column that holds it
INDICATOR_COLUMNS = {"rsi": "rsi_14", "obv": "obv", "stochastic": "stoch_k", "cci": "cci_20"}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_price_and_indicator(symbol: str, indicator_col: str, timeframe: str = "h1") -> pd.DataFrame:
    raw_conn = _conn(RAW_DB[symbol])
    try:
        with raw_conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, close_price FROM `{timeframe}` ORDER BY price_datetime ASC"
            )
            price_rows = cur.fetchall()
    finally:
        raw_conn.close()

    curated_conn = _conn(SILVER_DB[symbol])
    try:
        with curated_conn.cursor() as cur:
            cur.execute(
                f"SELECT bar_datetime AS price_datetime, {indicator_col} FROM features "
                "WHERE symbol=%s AND timeframe=%s ORDER BY bar_datetime ASC",
                (symbol, timeframe),
            )
            indicator_rows = cur.fetchall()
    finally:
        curated_conn.close()

    df_price = pd.DataFrame(price_rows)
    df_indicator = pd.DataFrame(indicator_rows)
    if df_price.empty or df_indicator.empty:
        return pd.DataFrame()

    merged = pd.merge(df_price, df_indicator, on="price_datetime", how="inner")
    merged["close_price"] = merged["close_price"].astype(float)
    merged[indicator_col] = merged[indicator_col].astype(float)
    return merged.sort_values("price_datetime").reset_index(drop=True)


def upsert_signals(symbol: str, signals: pd.DataFrame) -> int:
    if signals.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO divergence_signals
        (symbol, timeframe, bar_datetime, divergence_type, divergence_class, direction,
         prev_pivot_datetime, prev_pivot_price, prev_pivot_indicator,
         curr_pivot_datetime, curr_pivot_price, curr_pivot_indicator)
    VALUES
        (%(symbol)s, %(timeframe)s, %(bar_datetime)s, %(divergence_type)s, %(divergence_class)s, %(direction)s,
         %(prev_pivot_datetime)s, %(prev_pivot_price)s, %(prev_pivot_indicator)s,
         %(curr_pivot_datetime)s, %(curr_pivot_price)s, %(curr_pivot_indicator)s)
    ON DUPLICATE KEY UPDATE
        bar_datetime = VALUES(bar_datetime), direction = VALUES(direction),
        prev_pivot_datetime = VALUES(prev_pivot_datetime),
        prev_pivot_price = VALUES(prev_pivot_price), prev_pivot_indicator = VALUES(prev_pivot_indicator),
        curr_pivot_price = VALUES(curr_pivot_price), curr_pivot_indicator = VALUES(curr_pivot_indicator)
    """
    rows = signals.to_dict("records")
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(signals: pd.DataFrame, indicator_type: str, n_examples: int = 3):
    print(f"\nTotal divergence signals: {len(signals)}")
    if signals.empty:
        return
    print(signals.groupby(["divergence_class", "direction"]).size().to_string())

    print(f"\nFirst {n_examples} examples per (class, direction):")
    for (div_class, direction), group in signals.groupby(["divergence_class", "direction"]):
        for _, row in group.head(n_examples).iterrows():
            print(
                f"  [{div_class}/{direction}] confirmed_at={row['bar_datetime']}\n"
                f"    prev pivot: {row['prev_pivot_datetime']}  price={row['prev_pivot_price']:.5f}  {indicator_type}={row['prev_pivot_indicator']:.3f}\n"
                f"    curr pivot: {row['curr_pivot_datetime']}  price={row['curr_pivot_price']:.5f}  {indicator_type}={row['curr_pivot_indicator']:.3f}"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--indicator", default="rsi", choices=list(INDICATOR_COLUMNS))
    parser.add_argument("--pivot-window", type=int, default=3)
    parser.add_argument("--no-write", action="store_true", help="detect and report only, skip DB upsert")
    args = parser.parse_args()
    indicator_col = INDICATOR_COLUMNS[args.indicator]

    print(f"Loading {args.symbol} h1 price + {args.indicator} (from `{RAW_DB[args.symbol]}` + `{SILVER_DB[args.symbol]}`.features)...")
    df = load_price_and_indicator(args.symbol, indicator_col, "h1")
    if df.empty:
        print(f"No price+{args.indicator} data available for {args.symbol} — nothing to do.")
        return
    print(f"Loaded {len(df)} merged bars: {df['price_datetime'].min()} -> {df['price_datetime'].max()}")

    engine = TechnicalDivergenceEngine(pivot_window=args.pivot_window)
    signals = engine.detect(df, symbol=args.symbol, timeframe="h1", indicator_col=indicator_col, divergence_type=args.indicator)

    print_report(signals, args.indicator)

    if not args.no_write:
        n = upsert_signals(args.symbol, signals)
        print(f"\nUpserted {n} divergence signals into `{SILVER_DB[args.symbol]}`.divergence_signals")


if __name__ == "__main__":
    main()
