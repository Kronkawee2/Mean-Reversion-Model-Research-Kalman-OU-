"""
Runs HTFBiasEngine against real synced data (h1 primary, h4 CRT
equilibrium as secondary confirmation) and upserts one bias row per h1
bar into curated_<symbol>.htf_bias. Prints a summary + concrete examples
for manual/chart cross-checking, same pattern as the other run_*.py
scripts.

Pass 1 of strategies/ — HTF bias only. No LTF trigger logic, entry/stop/
target, or risk management here; see analysis/strategies/htf_bias_engine.py
module docstring for the full design and the three decisions confirmed
with the user before building (SMC-dominant weighting, h1 as primary
timeframe, ±50 bias threshold).

Usage:
    python scripts/detection/run_htf_bias_detection.py --symbol XAUUSD
    python scripts/detection/run_htf_bias_detection.py --symbol EURUSD --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.htf_bias_engine import HTFBiasEngine  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}

# Divergence types treated as "h1 technical" for the bias component (see
# module docstring: intermarket/d1 divergence is deliberately excluded
# from this pass's lookback-window mechanism).
H1_DIVERGENCE_TYPES = ("rsi", "obv", "stochastic", "cci")


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_h1_bars(symbol: str) -> pd.DataFrame:
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT price_datetime, close_price FROM h1 ORDER BY price_datetime ASC")
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_smc_zones(symbol: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT zone_type, state, created_at_bar, invalidated_at_bar FROM smc_signals "
                "WHERE symbol=%s AND timeframe='h1'", (symbol,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_crt_equilibrium(symbol: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_datetime, zone_bias FROM crt_signals "
                "WHERE symbol=%s AND timeframe='h4' AND signal_type='equilibrium'", (symbol,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_features_h1(symbol: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_datetime, ema_20, ema_50, ema_200, rsi_14 FROM features "
                "WHERE symbol=%s AND timeframe='h1'", (symbol,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    for col in ("ema_20", "ema_50", "ema_200", "rsi_14"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def load_volume_profile(symbol: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT session_date, session_poc FROM volume_profile "
                "WHERE symbol=%s AND timeframe='h1'", (symbol,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if "session_poc" in df.columns:
        df["session_poc"] = df["session_poc"].astype(float)
    return df


def load_liquidity_sweeps(symbol: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_datetime, direction FROM liquidity_sweeps "
                "WHERE symbol=%s AND timeframe='h1'", (symbol,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_divergence_h1(symbol: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(H1_DIVERGENCE_TYPES))
            cur.execute(
                f"SELECT bar_datetime, divergence_class, direction FROM divergence_signals "
                f"WHERE symbol=%s AND timeframe='h1' AND divergence_type IN ({fmt})",
                (symbol, *H1_DIVERGENCE_TYPES),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def upsert_bias(symbol: str, bias_rows: pd.DataFrame) -> int:
    if bias_rows.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO htf_bias
        (symbol, timeframe, bar_datetime, bias, confluence_score, raw_score_before_caution,
         smc_contribution, smc_active_bullish_zones, smc_active_bearish_zones,
         crt_contribution, crt_equilibrium_bias, indicator_contribution, volume_profile_contribution,
         hidden_divergence_contribution, hidden_divergence_count,
         regular_divergence_caution_factor, regular_divergence_count,
         liquidity_sweep_contribution, liquidity_sweep_direction, session, session_multiplier)
    VALUES
        (%(symbol)s, %(timeframe)s, %(bar_datetime)s, %(bias)s, %(confluence_score)s, %(raw_score_before_caution)s,
         %(smc_contribution)s, %(smc_active_bullish_zones)s, %(smc_active_bearish_zones)s,
         %(crt_contribution)s, %(crt_equilibrium_bias)s, %(indicator_contribution)s, %(volume_profile_contribution)s,
         %(hidden_divergence_contribution)s, %(hidden_divergence_count)s,
         %(regular_divergence_caution_factor)s, %(regular_divergence_count)s,
         %(liquidity_sweep_contribution)s, %(liquidity_sweep_direction)s, %(session)s, %(session_multiplier)s)
    ON DUPLICATE KEY UPDATE
        bias = VALUES(bias), confluence_score = VALUES(confluence_score),
        raw_score_before_caution = VALUES(raw_score_before_caution),
        smc_contribution = VALUES(smc_contribution),
        smc_active_bullish_zones = VALUES(smc_active_bullish_zones),
        smc_active_bearish_zones = VALUES(smc_active_bearish_zones),
        crt_contribution = VALUES(crt_contribution), crt_equilibrium_bias = VALUES(crt_equilibrium_bias),
        indicator_contribution = VALUES(indicator_contribution),
        volume_profile_contribution = VALUES(volume_profile_contribution),
        hidden_divergence_contribution = VALUES(hidden_divergence_contribution),
        hidden_divergence_count = VALUES(hidden_divergence_count),
        regular_divergence_caution_factor = VALUES(regular_divergence_caution_factor),
        regular_divergence_count = VALUES(regular_divergence_count),
        liquidity_sweep_contribution = VALUES(liquidity_sweep_contribution),
        liquidity_sweep_direction = VALUES(liquidity_sweep_direction),
        session = VALUES(session), session_multiplier = VALUES(session_multiplier)
    """
    rows = bias_rows.to_dict("records")
    for row in rows:
        if pd.isna(row.get("crt_equilibrium_bias")):
            row["crt_equilibrium_bias"] = None
        if pd.isna(row.get("liquidity_sweep_direction")) or row.get("liquidity_sweep_direction") is None:
            row["liquidity_sweep_direction"] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(bias_rows: pd.DataFrame, n_examples: int = 5):
    print(f"\nTotal bias rows: {len(bias_rows)}")
    if bias_rows.empty:
        return
    print(bias_rows["bias"].value_counts().to_string())

    print(f"\nLast {n_examples} bars:")
    for _, row in bias_rows.tail(n_examples).iterrows():
        print(
            f"  {row['bar_datetime']}  bias={row['bias']:8s}  score={row['confluence_score']:7.2f}  "
            f"smc={row['smc_contribution']:+.1f}({row['smc_active_bullish_zones']}b/{row['smc_active_bearish_zones']}be)  "
            f"crt={row['crt_contribution']:+.1f}({row['crt_equilibrium_bias']})  "
            f"ind={row['indicator_contribution']:+.1f}  vp={row['volume_profile_contribution']:+.1f}  "
            f"hidden={row['hidden_divergence_contribution']:+.1f}({row['hidden_divergence_count']})  "
            f"caution={row['regular_divergence_caution_factor']:.3f}({row['regular_divergence_count']})  "
            f"sweep={row['liquidity_sweep_contribution']:+.1f}({row['liquidity_sweep_direction']})  "
            f"session={row['session']}(x{row['session_multiplier']})"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} h1 bars + SMC/CRT/features/volume-profile/divergence from `{SILVER_DB[symbol]}`...")
    h1_bars = load_h1_bars(symbol)
    if h1_bars.empty:
        print(f"No h1 data available for {symbol} — nothing to do.")
        return
    print(f"Loaded {len(h1_bars)} h1 bars: {h1_bars['price_datetime'].min()} -> {h1_bars['price_datetime'].max()}")

    smc_zones = load_smc_zones(symbol)
    crt_equilibrium = load_crt_equilibrium(symbol)
    features_h1 = load_features_h1(symbol)
    volume_profile = load_volume_profile(symbol)
    divergence_h1 = load_divergence_h1(symbol)
    liquidity_sweeps = load_liquidity_sweeps(symbol)
    print(f"Inputs: {len(smc_zones)} SMC zones, {len(crt_equilibrium)} CRT equilibrium rows (h4), "
          f"{len(features_h1)} feature rows, {len(volume_profile)} sessions, {len(divergence_h1)} h1 divergence signals, "
          f"{len(liquidity_sweeps)} liquidity sweeps")

    engine = HTFBiasEngine()
    bias_rows = engine.compute_bias(
        h1_bars, smc_zones, crt_equilibrium, features_h1, volume_profile, divergence_h1, liquidity_sweeps,
        symbol=symbol, timeframe="h1",
    )

    print_report(bias_rows)

    if not args.no_write:
        n = upsert_bias(symbol, bias_rows)
        print(f"\nUpserted {n} bias rows into `{SILVER_DB[symbol]}`.htf_bias")


if __name__ == "__main__":
    main()
