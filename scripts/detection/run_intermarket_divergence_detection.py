"""
Runs IntermarketDivergenceEngine against real synced d1 price data
(primary asset's d1 close, resampled from MT5 h1 -- see
load_primary_d1_close() below; raw_<primary>.d1 is deprecated Yahoo-sourced
data as of the d1 MT5-migration decision, see docs/DECISIONS.md) merged
with a driver series and upserts the resulting Regular + Hidden Bullish/
Bearish divergence signals into curated_<primary>.divergence_signals.
Prints a summary + concrete examples for manual/chart cross-checking, same
pattern as the other run_*.py scripts.

Three drivers -- DXY (xau_dxy/eur_dxy) and Silver (xau_xag) -- are ALSO
resampled from MT5 h1 now (raw_dxy.h1 via USDX, raw_silver.h1 via XAGUSD)
rather than read from their own deprecated Yahoo d1 tables, as of the
Silver/DXY/VIX MT5-migration decision (see docs/DECISIONS.md). US10Y/GDX
have no MT5 equivalent (no bond/yield instrument, no gold-miner ETF on
Eightcap) and stay Yahoo-sourced. VIX has no divergence model in
INTERMARKET_MODELS currently, so its migration doesn't touch this file.

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
from analysis.rolling_window import rolling_window_start  # noqa: E402
from analysis.features.indicator_features import resample_ohlc  # noqa: E402

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
# xau_dxy/eur_dxy/xau_xag's "table": "h1" entries are cosmetic (header-print
# only, like eur_yield_spread's) -- RESAMPLED_H1_DRIVERS below is what
# actually routes them through the resample-from-h1 path instead of
# _load_single_source().
DRIVER_SOURCE = {
    "xau_dxy":   {"db": "raw_dxy",  "table": "h1 (resampled)",   "date_col": "price_datetime", "value_col": "close_price"},
    "eur_dxy":   {"db": "raw_dxy",  "table": "h1 (resampled)",   "date_col": "price_datetime", "value_col": "close_price"},
    "xau_us10y": {"db": "raw_us10y", "table": "d1",  "date_col": "price_datetime", "value_col": "close_price"},
    "xau_gdx":   {"db": "raw_gdx",  "table": "d1",   "date_col": "price_datetime", "value_col": "close_price"},
    "cot_gold":  {"db": "raw_cot",  "table": "gold", "date_col": "report_date",    "value_col": "commercial_net_position"},
    "cot_eur":   {"db": "raw_cot",  "table": "eur",  "date_col": "report_date",    "value_col": "commercial_net_position"},
    "xau_spdr":  {"db": "raw_spdr", "table": "gld",  "date_col": "report_date",    "value_col": "tonnes_of_gold"},
    "xau_gpr":   {"db": "raw_gpr",  "table": "gpr",  "date_col": "report_date",    "value_col": "gprd"},
    "xau_xag":   {"db": "raw_silver", "table": "h1 (resampled)", "date_col": "price_datetime", "value_col": "close_price"},
    "xau_tips":     {"db": "raw_fred", "table": "tips10y",   "date_col": "report_date", "value_col": "real_yield_pct"},
    "xau_fedfunds": {"db": "raw_fred", "table": "fed_funds", "date_col": "report_date", "value_col": "rate_pct"},
    "xau_cpi":      {"db": "raw_fred", "table": "cpi",       "date_col": "report_date", "value_col": "cpi_index"},
    # Not a single-source entry -- load_driver() special-cases this one to
    # compute US10Y-EU10Y from two raw sources (see _load_yield_spread()).
    # Kept here only for run_one()'s header print, not used to load data.
    "eur_yield_spread": {"db": "raw_us10y+raw_ecb", "table": "d1+eu10y", "date_col": "-", "value_col": "-"},
}

# divergence_type -> raw_<db> to resample h1 -> d1 from, MT5-sourced (USDX
# for DXY, XAGUSD for Silver) -- replaces raw_dxy.d1/raw_silver.d1 (Yahoo
# DX-Y.NYB/SI=F, both deprecated: DST-anchoring bug plus, for DXY, a
# near-total row-duplication bug, see docs/DECISIONS.md).
RESAMPLED_H1_DRIVERS = {
    "xau_dxy": "raw_dxy",
    "eur_dxy": "raw_dxy",
    "xau_xag": "raw_silver",
}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_primary_d1_close(symbol: str) -> pd.DataFrame:
    """d1 resampled from MT5 h1 (same RESAMPLE_RULE pattern as
    run_feature_engineering.py/run_crt_detection.py/dashboard/1_Chart.py) --
    raw_<symbol>.d1 (Yahoo GC=F/EURUSD=X) is deprecated: 36.1% of gold's and
    58.3% of eurusd's Yahoo-sourced d1 rows sat on a DST-shifted
    America/New_York-anchored grid rather than fixed UTC midnight, see
    docs/DECISIONS.md. h1 is already rolling-window-filtered here, same as
    every other query in this script."""
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price_datetime, open_price, high_price, low_price, close_price FROM h1 "
                "WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df_h1 = pd.DataFrame(rows)
    if df_h1.empty:
        return df_h1
    df = resample_ohlc(df_h1, rule="1d")
    df["close_price"] = df["close_price"].astype(float)
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    return df[["price_datetime", "close_price"]]


def _load_single_source(db, table, date_col, value_col) -> pd.DataFrame:
    # 90-day buffer before the rolling-window cutoff so merge_asof(direction=
    # "backward") in load_merged() still has a driver value to carry forward
    # into the first few primary bars of the window -- otherwise a weekly
    # (COT) or monthly (CPI/Fed Funds) driver whose most recent pre-cutoff
    # report falls a few days/weeks before the cutoff would leave those early
    # primary bars with no driver match and get dropped.
    import datetime
    buffered_cutoff = rolling_window_start() - datetime.timedelta(days=90)
    conn = _conn(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {date_col}, {value_col} FROM `{table}` WHERE {date_col} >= %s ORDER BY {date_col} ASC",
                (buffered_cutoff,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns={date_col: "price_datetime", value_col: "driver_close"})
    # pymysql returns DATE columns (report_date) as datetime.date and
    # DATETIME columns (price_datetime) as datetime.datetime -- pandas
    # infers a different unit for each, which merge_asof refuses to join
    # on without coercing both to the same unit first (same root cause and
    # fix as run_intermarket_divergence_detection.py's earlier dtype bug).
    df["price_datetime"] = pd.to_datetime(df["price_datetime"]).astype("datetime64[us]")
    df["driver_close"] = df["driver_close"].astype(float)
    return df.dropna(subset=["driver_close"])


def _load_driver_from_h1(db) -> pd.DataFrame:
    """Resamples raw_<db>.h1 (MT5-sourced) -> d1, same rolling-window +
    resample_ohlc pattern as load_primary_d1_close() above -- used for
    DXY (raw_dxy.h1, USDX) and Silver (raw_silver.h1, XAGUSD) drivers
    instead of reading their deprecated Yahoo d1 tables."""
    conn = _conn(db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT price_datetime, open_price, high_price, low_price, close_price FROM h1 "
                "WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df_h1 = pd.DataFrame(rows)
    if df_h1.empty:
        return df_h1
    df = resample_ohlc(df_h1, rule="1d")
    df = df.rename(columns={"close_price": "driver_close"})
    df["driver_close"] = df["driver_close"].astype(float)
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    return df[["price_datetime", "driver_close"]]


def _load_yield_spread() -> pd.DataFrame:
    """
    eur_yield_spread's driver isn't a single raw column like every other
    model in DRIVER_SOURCE -- it's the US10Y-EU10Y differential (the FX
    carry-trade driver), computed from two separate raw sources
    (raw_us10y.d1, raw_ecb.eu10y) since neither alone is the actual
    theorized driver. Confirmed empirically before wiring this in: EURUSD
    vs spread price-level correlation -0.79, daily-change correlation
    -0.07 across 5,676 matched bars -- the cleanest and strongest-signed
    correlation of any driver added this round. Closes the "EUR vs
    yield-spread" item noted as indefinitely deferred in
    intermarket_divergence_state.py's module docstring.
    """
    us10y = _load_single_source("raw_us10y", "d1", "price_datetime", "close_price").rename(
        columns={"driver_close": "us10y"})
    eu10y = _load_single_source("raw_ecb", "eu10y", "report_date", "yield_pct").rename(
        columns={"driver_close": "eu10y"})
    if us10y.empty or eu10y.empty:
        return pd.DataFrame()
    merged = pd.merge_asof(
        us10y.sort_values("price_datetime"), eu10y[["price_datetime", "eu10y"]].sort_values("price_datetime"),
        on="price_datetime", direction="backward",
    ).dropna(subset=["us10y", "eu10y"])
    merged["driver_close"] = merged["us10y"] - merged["eu10y"]
    return merged[["price_datetime", "driver_close"]]


def load_driver(divergence_type: str) -> pd.DataFrame:
    if divergence_type == "eur_yield_spread":
        return _load_yield_spread()
    if divergence_type in RESAMPLED_H1_DRIVERS:
        return _load_driver_from_h1(RESAMPLED_H1_DRIVERS[divergence_type])
    src = DRIVER_SOURCE[divergence_type]
    return _load_single_source(src["db"], src["table"], src["date_col"], src["value_col"])


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
    #
    # pymysql returns DATE columns (COT's report_date, SPDR's report_date)
    # as datetime.date and DATETIME columns (every OHLCV price_datetime)
    # as datetime.datetime -- pandas infers a different unit for each
    # (datetime64[s] vs datetime64[us]), which merge_asof refuses to join
    # on directly. Both sides already went through pd.to_datetime() above;
    # just normalize the unit right before the merge.
    primary_df["price_datetime"] = primary_df["price_datetime"].astype("datetime64[us]")
    driver_df["price_datetime"] = driver_df["price_datetime"].astype("datetime64[us]")
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
