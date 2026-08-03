"""
Quick Bronze data sync — fetch latest OHLCV from Yahoo Finance and upsert into MySQL.
Covers: XAUUSD (gold), EURUSD (eurusd), DXY, VIX (daily).
"""

import sys
import pymysql
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

DB = dict(host="localhost", port=3306, user="gold_user", password="1234", charset="utf8mb4")

# Symbol → (database, table_prefix, yf_ticker, rounding_decimals)
ASSETS = {
    "XAUUSD": ("gold",   "GC=F",      2),
    "EURUSD": ("eurusd", "EURUSD=X",  5),
    "DXY":    ("dxy",    "DX-Y.NYB",  3),
    "VIX":    ("vix",    "^VIX",      2),
    "GDX":    ("gdx",    "GDX",       2),
    "US10Y":  ("us10y",  "^TNX",      3),
}

TIMEFRAMES = {
    "m5":  "5m",
    "m15": "15m",
    "h1":  "1h",
    "h4":  "4h",
    "d1":  "1d",
}

# Which timeframes each asset supports (yfinance limitations)
ASSET_TF = {
    "XAUUSD": ["m5", "m15", "h1", "h4", "d1"],
    "EURUSD": ["m5", "m15", "h1", "h4", "d1"],
    "DXY":    ["h1", "d1"],
    "VIX":    ["d1"],
    "GDX":    ["d1"],
    "US10Y":  ["d1"],
}

# yfinance period to use based on interval (max lookback)
PERIOD_MAP = {
    "5m":  "60d",
    "15m": "60d",
    "1h":  "730d",
    "4h":  "730d",
    "1d":  "max",
}


def get_conn(database=None):
    kwargs = dict(**DB)
    if database:
        kwargs["database"] = database
    return pymysql.connect(**kwargs, cursorclass=pymysql.cursors.DictCursor)


def ensure_table(conn, table: str):
    """Create OHLCV table if not exists."""
    sql = f"""
    CREATE TABLE IF NOT EXISTS `{table}` (
        id            BIGINT AUTO_INCREMENT PRIMARY KEY,
        price_date    DATE        NOT NULL,
        price_datetime DATETIME   NOT NULL UNIQUE,
        open_price    DECIMAL(16,5) NOT NULL,
        high_price    DECIMAL(16,5) NOT NULL,
        low_price     DECIMAL(16,5) NOT NULL,
        close_price   DECIMAL(16,5) NOT NULL,
        volume        BIGINT DEFAULT 0,
        inserted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def get_latest_dt(conn, table: str):
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT MAX(price_datetime) as mx FROM `{table}`")
            row = cur.fetchone()
            return row["mx"] if row and row["mx"] else None
    except Exception:
        return None


def upsert_rows(conn, table: str, rows: list, dec: int) -> int:
    if not rows:
        return 0
    sql = f"""
    INSERT INTO `{table}`
        (price_date, price_datetime, open_price, high_price, low_price, close_price, volume)
    VALUES
        (%(date)s, %(dt)s, %(o)s, %(h)s, %(l)s, %(c)s, %(v)s)
    ON DUPLICATE KEY UPDATE
        open_price  = VALUES(open_price),
        high_price  = VALUES(high_price),
        low_price   = VALUES(low_price),
        close_price = VALUES(close_price),
        volume      = VALUES(volume)
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    conn.commit()
    return len(rows)


def fetch_and_sync(asset_name: str):
    db_name, ticker_sym, dec = ASSETS[asset_name]
    tfs = ASSET_TF[asset_name]

    print(f"\n{'='*50}")
    print(f"Syncing {asset_name} -> db: {db_name}  ticker: {ticker_sym}")

    conn = get_conn(db_name)
    total_new = 0

    for tf in tfs:
        table    = tf
        interval = TIMEFRAMES[tf]
        period   = PERIOD_MAP[interval]

        ensure_table(conn, table)
        latest = get_latest_dt(conn, table)

        try:
            df = yf.download(
                ticker_sym,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                multi_level_index=False,
            )
        except Exception as e:
            print(f"  [{tf}] Download error: {e}")
            continue

        if df is None or df.empty:
            print(f"  [{tf}] No data returned")
            continue

        df.index = pd.to_datetime(df.index).tz_localize(None)

        if latest:
            df = df[df.index > pd.Timestamp(latest)]

        if df.empty:
            print(f"  [{tf}] Already up to date (latest: {latest})")
            continue

        rows = []
        for dt_idx, row in df.iterrows():
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            v = int(row.get("Volume", 0) or 0)
            if pd.isna(o) or pd.isna(c):
                continue
            rows.append({
                "date": dt_idx.date(),
                "dt":   dt_idx.strftime("%Y-%m-%d %H:%M:%S"),
                "o":    round(o, dec),
                "h":    round(h, dec),
                "l":    round(l, dec),
                "c":    round(c, dec),
                "v":    v,
            })

        n = upsert_rows(conn, table, rows, dec)
        total_new += n
        new_latest = df.index[-1].strftime("%Y-%m-%d %H:%M")
        print(f"  [{tf}] +{n} rows -> latest now: {new_latest}")

    conn.close()
    print(f"  {asset_name} done: {total_new} total rows inserted/updated")
    return total_new


if __name__ == "__main__":
    start = datetime.now()
    grand_total = 0

    targets = sys.argv[1:] if len(sys.argv) > 1 else list(ASSETS.keys())

    for name in targets:
        if name not in ASSETS:
            print(f"Unknown asset: {name}")
            continue
        grand_total += fetch_and_sync(name)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{'='*50}")
    print(f"Sync complete: {grand_total} rows total in {elapsed:.1f}s")
