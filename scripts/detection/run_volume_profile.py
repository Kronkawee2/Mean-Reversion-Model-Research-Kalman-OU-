"""
Runs SessionVolumeProfileEngine against real synced h1 OHLCV data and
upserts the resulting bin rows into curated_<symbol>.volume_profile. Also
prints a summary report (POC/VAH/VAL + HVN/LVN per session) for manual
sanity-checking, same pattern as run_smc_zone_detection.py /
run_crt_detection.py / run_feature_engineering.py.

Timeframe is always h1 (see analysis/volume_profile/session_profile.py
module docstring for why h1-only and per-UTC-session-day were chosen).

Usage:
    python scripts/detection/run_volume_profile.py --symbol XAUUSD
    python scripts/detection/run_volume_profile.py --symbol EURUSD --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.volume_profile.session_profile import SessionVolumeProfileEngine  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}


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


def upsert_bins(symbol: str, bins: pd.DataFrame) -> int:
    if bins.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO volume_profile
        (symbol, timeframe, session_date, bin_index, bin_low, bin_high, bin_center, bin_volume,
         is_poc, in_value_area, is_hvn, is_lvn,
         session_poc, session_vah, session_val, session_total_volume, num_bins)
    VALUES
        (%(symbol)s, %(timeframe)s, %(session_date)s, %(bin_index)s, %(bin_low)s, %(bin_high)s,
         %(bin_center)s, %(bin_volume)s, %(is_poc)s, %(in_value_area)s, %(is_hvn)s, %(is_lvn)s,
         %(session_poc)s, %(session_vah)s, %(session_val)s, %(session_total_volume)s, %(num_bins)s)
    ON DUPLICATE KEY UPDATE
        bin_low = VALUES(bin_low), bin_high = VALUES(bin_high), bin_center = VALUES(bin_center),
        bin_volume = VALUES(bin_volume), is_poc = VALUES(is_poc), in_value_area = VALUES(in_value_area),
        is_hvn = VALUES(is_hvn), is_lvn = VALUES(is_lvn),
        session_poc = VALUES(session_poc), session_vah = VALUES(session_vah), session_val = VALUES(session_val),
        session_total_volume = VALUES(session_total_volume), num_bins = VALUES(num_bins)
    """
    rows = bins.to_dict("records")
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(bins: pd.DataFrame, n_sessions: int = 5):
    print(f"\nTotal bin rows: {len(bins)}")
    if bins.empty:
        return
    sessions = sorted(bins["session_date"].unique())
    print(f"Sessions covered: {len(sessions)} ({sessions[0]} -> {sessions[-1]})")

    print(f"\nFirst {n_sessions} sessions (POC/VAH/VAL + HVN/LVN levels):")
    for sd in sessions[:n_sessions]:
        day = bins[bins["session_date"] == sd]
        poc = day["session_poc"].iloc[0]
        vah = day["session_vah"].iloc[0]
        val = day["session_val"].iloc[0]
        total_vol = day["session_total_volume"].iloc[0]
        hvn_levels = sorted(day[day["is_hvn"]]["bin_center"].tolist())
        lvn_levels = sorted(day[day["is_lvn"]]["bin_center"].tolist())
        print(f"  {sd}: POC={poc:.5f}  VAH={vah:.5f}  VAL={val:.5f}  total_vol={total_vol:.0f}")
        print(f"    HVN: {[round(x, 5) for x in hvn_levels]}")
        print(f"    LVN: {[round(x, 5) for x in lvn_levels]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--num-bins", type=int, default=50)
    parser.add_argument("--value-area-pct", type=float, default=0.70)
    parser.add_argument("--no-write", action="store_true", help="detect and report only, skip DB upsert")
    args = parser.parse_args()

    print(f"Loading {args.symbol} h1 from `{RAW_DB[args.symbol]}`...")
    df = load_ohlcv(args.symbol, "h1")
    if df.empty:
        print(f"No h1 data available for {args.symbol} — nothing to do.")
        return
    print(f"Loaded {len(df)} h1 bars: {df['price_datetime'].min()} -> {df['price_datetime'].max()}")

    engine = SessionVolumeProfileEngine(num_bins=args.num_bins, value_area_pct=args.value_area_pct)
    bins = engine.compute_session_profiles(df, symbol=args.symbol, timeframe="h1")

    print_report(bins)

    if not args.no_write:
        n = upsert_bins(args.symbol, bins)
        print(f"\nUpserted {n} bin rows into `{SILVER_DB[args.symbol]}`.volume_profile")


if __name__ == "__main__":
    main()
