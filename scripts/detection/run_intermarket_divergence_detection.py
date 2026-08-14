"""
Runs IntermarketDivergenceEngine against real synced d1 price data
(primary asset always from raw_<primary>.d1) merged with a driver series
and upserts the resulting Regular + Hidden Bullish/Bearish divergence
signals into curated_<primary>.divergence_signals. Prints a summary +
concrete examples for manual/chart cross-checking, same pattern as the
other run_*.py scripts.

7 models total now: xau_dxy, eur_dxy, xau_us10y, xau_gdx (Phase 2h, all
OHLCV d1 drivers) plus cot_gold, cot_eur, xau_spdr (Phase 2i, weekly COT
and daily SPDR holdings drivers — see DRIVER_SOURCE below for how each
source's shape differs; IntermarketDivergenceEngine itself needed no
changes for either phase). EUR vs yield-spread remains deferred
indefinitely (no EU/German yield source exists).

Usage:
    python scripts/detection/run_intermarket_divergence_detection.py --model xau_dxy
    python scripts/detection/run_intermarket_divergence_detection.py --model cot_gold --no-write
    python scripts/detection/run_intermarket_divergence_detection.py --model all
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.divergence.intermarket_divergence_state import IntermarketDivergenceEngine, INTERMARKET_MODELS  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}

# divergence_type -> (driver database, table, date column, value column).
# Every driver ends up as (price_datetime, driver_close) after loading,
# regardless of its native column names, so load_merged() below stays
# generic across OHLCV drivers (DXY/US10Y/GDX), weekly COT, and daily SPDR.
DRIVER_SOURCE = {
    "xau_dxy":   {"db": "raw_dxy",  "table": "d1",   "date_col": "price_datetime", "value_col": "close_price"},
    "eur_dxy":   {"db": "raw_dxy",  "table": "d1",   "date_col": "price_datetime", "value_col": "close_price"},
    "xau_us10y": {"db": "raw_us10y", "table": "d1",  "date_col": "price_datetime", "value_col": "close_price"},
    "xau_gdx":   {"db": "raw_gdx",  "table": "d1",   "date_col": "price_datetime", "value_col": "close_price"},
    "cot_gold":  {"db": "raw_cot",  "table": "gold", "date_col": "report_date",    "value_col": "commercial_net_position"},
    "cot_eur":   {"db": "raw_cot",  "table": "eur",  "date_col": "report_date",    "value_col": "commercial_net_position"},
    "xau_spdr":  {"db": "raw_spdr", "table": "gld",  "date_col": "report_date",    "value_col": "tonnes_of_gold"},
}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_primary_d1_close(symbol: str) -> pd.DataFrame:
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT price_datetime, close_price FROM d1 ORDER BY price_datetime ASC")
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["close_price"] = df["close_price"].astype(float)
        df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    return df


def load_driver(divergence_type: str) -> pd.DataFrame:
    src = DRIVER_SOURCE[divergence_type]
    conn = _conn(src["db"])
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {src['date_col']}, {src['value_col']} FROM `{src['table']}` ORDER BY {src['date_col']} ASC")
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns={src["date_col"]: "price_datetime", src["value_col"]: "driver_close"})
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    df["driver_close"] = df["driver_close"].astype(float)
    return df.dropna(subset=["driver_close"])


def load_merged(divergence_type: str) -> pd.DataFrame:
    cfg = INTERMARKET_MODELS[divergence_type]
    primary_df = load_primary_d1_close(cfg["primary"])
    driver_df = load_driver(divergence_type)
    if primary_df.empty or driver_df.empty:
        return pd.DataFrame()

    # backward-asof: at each daily primary bar, use the most recent driver
    # value known as of that date. For weekly COT this carries the last
    # report forward until the next one (causal, same principle as the
    # OHLCV drivers); for daily SPDR it's effectively a same-day join.
    merged = pd.merge_asof(
        primary_df.sort_values("price_datetime"),
        driver_df.sort_values("price_datetime"),
        on="price_datetime", direction="backward",
    )
    return merged.dropna(subset=["driver_close"]).reset_index(drop=True)


def upsert_signals(primary_symbol: str, signals: pd.DataFrame) -> int:
    if signals.empty:
        return 0
    conn = _conn(SILVER_DB[primary_symbol])
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


def print_report(divergence_type: str, signals: pd.DataFrame, n_examples: int = 3):
    print(f"\n[{divergence_type}] Total divergence signals: {len(signals)}")
    if signals.empty:
        return
    print(signals.groupby(["divergence_class", "direction"]).size().to_string())

    print(f"[{divergence_type}] First {n_examples} examples per (class, direction):")
    for (div_class, direction), group in signals.groupby(["divergence_class", "direction"]):
        for _, row in group.head(n_examples).iterrows():
            print(
                f"  [{div_class}/{direction}] confirmed_at={row['bar_datetime']}\n"
                f"    prev pivot: {row['prev_pivot_datetime']}  primary={row['prev_pivot_price']:.5f}  driver={row['prev_pivot_indicator']:.5f}\n"
                f"    curr pivot: {row['curr_pivot_datetime']}  primary={row['curr_pivot_price']:.5f}  driver={row['curr_pivot_indicator']:.5f}"
            )


def run_one(divergence_type: str, pivot_window: int, no_write: bool):
    cfg = INTERMARKET_MODELS[divergence_type]
    primary_symbol = cfg["primary"]
    relationship = cfg["relationship"]
    src = DRIVER_SOURCE[divergence_type]

    print(f"\n=== {divergence_type} ({primary_symbol} vs {src['db']}.{src['table']}, {relationship}) ===")
    df = load_merged(divergence_type)
    if df.empty:
        print(f"No merged data available for {divergence_type} — skipping.")
        return
    print(f"Loaded {len(df)} merged bars: {df['price_datetime'].min()} -> {df['price_datetime'].max()}")

    engine = IntermarketDivergenceEngine(pivot_window=pivot_window)
    signals = engine.detect(df, symbol=primary_symbol, timeframe="d1", divergence_type=divergence_type, relationship=relationship)

    print_report(divergence_type, signals)

    if not no_write:
        n = upsert_signals(primary_symbol, signals)
        print(f"[{divergence_type}] Upserted {n} divergence signals into `{SILVER_DB[primary_symbol]}`.divergence_signals")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="all", choices=list(INTERMARKET_MODELS) + ["all"])
    parser.add_argument("--pivot-window", type=int, default=3)
    parser.add_argument("--no-write", action="store_true", help="detect and report only, skip DB upsert")
    args = parser.parse_args()

    models = list(INTERMARKET_MODELS) if args.model == "all" else [args.model]
    for divergence_type in models:
        run_one(divergence_type, args.pivot_window, args.no_write)


if __name__ == "__main__":
    main()
