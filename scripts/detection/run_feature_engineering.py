"""
Runs calc_indicator_features (EMA 20/50/200, ATR 14, RSI 14) against real
synced OHLCV data across h1/h4/h6/d1 and upserts into
curated_<symbol>.features. h6 is derived by resampling h1 (see
analysis/features/indicator_features.py docstring for why). Prints a
summary + sample rows for manual/external cross-checking, same pattern as
run_smc_zone_detection.py / run_crt_detection.py.

Usage:
    python scripts/detection/run_feature_engineering.py --symbol XAUUSD
    python scripts/detection/run_feature_engineering.py --symbol EURUSD --timeframes h4,d1 --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.features.indicator_features import calc_indicator_features, resample_ohlc  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
ALL_TIMEFRAMES = ["h1", "h4", "h6", "d1"]


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_ohlcv(symbol: str, timeframe: str) -> pd.DataFrame:
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, open_price, high_price, low_price, close_price, volume "
                f"FROM `{timeframe}` ORDER BY price_datetime ASC"
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def upsert_features(symbol: str, features: pd.DataFrame) -> int:
    if features.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO features
        (symbol, timeframe, bar_datetime, ema_20, ema_50, ema_200, atr_14, rsi_14, obv, stoch_k, stoch_d, cci_20)
    VALUES
        (%(symbol)s, %(timeframe)s, %(bar_datetime)s, %(ema_20)s, %(ema_50)s, %(ema_200)s, %(atr_14)s, %(rsi_14)s, %(obv)s,
         %(stoch_k)s, %(stoch_d)s, %(cci_20)s)
    ON DUPLICATE KEY UPDATE
        ema_20 = VALUES(ema_20),
        ema_50 = VALUES(ema_50),
        ema_200 = VALUES(ema_200),
        atr_14 = VALUES(atr_14),
        rsi_14 = VALUES(rsi_14),
        obv = VALUES(obv),
        stoch_k = VALUES(stoch_k),
        stoch_d = VALUES(stoch_d),
        cci_20 = VALUES(cci_20)
    """
    rows = features.to_dict("records")
    for row in rows:
        for key in ("ema_20", "ema_50", "ema_200", "atr_14", "rsi_14", "obv", "stoch_k", "stoch_d", "cci_20"):
            if pd.isna(row[key]):
                row[key] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(timeframe: str, features: pd.DataFrame, n: int = 5):
    print(f"\n[{timeframe}] Total feature rows: {len(features)}")
    if features.empty:
        return
    valid = features.dropna(subset=["ema_200"])
    print(f"[{timeframe}] Rows with all indicators warmed up (ema_200 non-null): {len(valid)}")
    print(f"[{timeframe}] Last {n} rows:")
    for _, row in features.tail(n).iterrows():
        print(
            f"  {row['bar_datetime']}  ema20={row['ema_20']:.5f}  ema50={row['ema_50']:.5f}  "
            f"ema200={row['ema_200'] if pd.notnull(row['ema_200']) else float('nan'):.5f}  "
            f"atr14={row['atr_14']:.5f}  rsi14={row['rsi_14']:.3f}  obv={row['obv']:.1f}  "
            f"stochK={row['stoch_k'] if pd.notnull(row['stoch_k']) else float('nan'):.3f}  "
            f"stochD={row['stoch_d'] if pd.notnull(row['stoch_d']) else float('nan'):.3f}  "
            f"cci20={row['cci_20'] if pd.notnull(row['cci_20']) else float('nan'):.3f}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--timeframes", default=",".join(ALL_TIMEFRAMES),
                         help="comma-separated subset of h1,h4,h6,d1")
    parser.add_argument("--no-write", action="store_true", help="detect and report only, skip DB upsert")
    args = parser.parse_args()
    timeframes = args.timeframes.split(",")

    df_h1 = None
    total_written = 0
    for tf in timeframes:
        if tf == "h6":
            if df_h1 is None:
                df_h1 = load_ohlcv(args.symbol, "h1")
            if df_h1.empty:
                print(f"\n[h6] No h1 data available for {args.symbol} to resample from — skipping.")
                continue
            df = resample_ohlc(df_h1, rule="6h")
            print(f"\nResampled {len(df_h1)} h1 bars -> {len(df)} h6 bars for {args.symbol}")
        else:
            df = load_ohlcv(args.symbol, tf)
            if tf == "h1":
                df_h1 = df
            if df.empty:
                print(f"\n[{tf}] No data available for {args.symbol} — skipping.")
                continue
            print(f"\nLoaded {len(df)} {tf} bars for {args.symbol}: "
                  f"{df['price_datetime'].min()} -> {df['price_datetime'].max()}")

        features = calc_indicator_features(df, symbol=args.symbol, timeframe=tf)
        print_report(tf, features)

        if not args.no_write:
            n = upsert_features(args.symbol, features)
            total_written += n
            print(f"[{tf}] Upserted {n} feature rows into `{SILVER_DB[args.symbol]}`.features")

    if not args.no_write:
        print(f"\nTotal upserted across all timeframes: {total_written}")


if __name__ == "__main__":
    main()
