"""
Runs analysis/strategies/nested_zone_engine.py against real data and
upserts every valid (LTF-terminated) chain into
curated_<symbol>.nested_zone_chains, plus any newly-detected M15/M5 zones
into curated_<symbol>.ltf_smc_zones (dashboard reference only -- the
composite engine never reads ltf_smc_zones directly, it reads
nested_zone_chains).

This is currently a STANDALONE detection pass, not wired into
run_detection.py -- per the side-by-side comparison run against the
current H1-touch mechanism, Nested Zone Drilling has NOT replaced or
supplemented production candidate generation yet (see docs/DECISIONS.md
for the real numbers). Run manually until/unless that decision changes.

Bounded by a shorter recency window than the rest of the pipeline
(NESTED_WINDOW_DAYS, not the shared 2-year rolling window) -- drilling
runs SMCZoneStateEngine fresh per candidate root zone (M15/M5 zone
detection was never persisted before this), which is too expensive to run
across years of roots in one pass.

Usage:
    python scripts/detection/run_nested_zone_drilling.py --symbol XAUUSD
    python scripts/detection/run_nested_zone_drilling.py --symbol XAUUSD --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies import nested_zone_engine as nze  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
NESTED_WINDOW_DAYS = 60


def _conn(database):
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                            database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def load(sql, db, params=()):
    conn = _conn(db)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.close()
    return pd.DataFrame(rows)


def load_zones(symbol, tf, since):
    z = load("SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar, state "
              "FROM smc_signals WHERE symbol=%s AND timeframe=%s AND created_at_bar >= %s",
              SILVER_DB[symbol], (symbol, tf, since))
    if z.empty:
        return z
    z["created_at_bar"] = pd.to_datetime(z["created_at_bar"])
    z["invalidated_at_bar"] = pd.to_datetime(z["invalidated_at_bar"])
    for c in ("zone_top", "zone_bottom"):
        z[c] = z[c].astype(float)
    return z


def persist_chains(symbol, chains):
    import json
    if not chains:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO nested_zone_chains
        (symbol, direction, root_timeframe, terminal_timeframe, chain,
         zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar)
    VALUES
        (%(symbol)s, %(direction)s, %(root_timeframe)s, %(terminal_timeframe)s, %(chain)s,
         %(zone_type)s, %(zone_top)s, %(zone_bottom)s, %(created_at_bar)s, %(invalidated_at_bar)s)
    ON DUPLICATE KEY UPDATE
        direction=VALUES(direction), root_timeframe=VALUES(root_timeframe), chain=VALUES(chain),
        invalidated_at_bar=VALUES(invalidated_at_bar)
    """
    rows = []
    for c in chains:
        rows.append({
            "symbol": c["symbol"], "direction": c["direction"], "root_timeframe": c["root_timeframe"],
            "terminal_timeframe": c["terminal_timeframe"], "chain": json.dumps(c["chain"]),
            "zone_type": c["zone_type"], "zone_top": c["zone_top"], "zone_bottom": c["zone_bottom"],
            "created_at_bar": pd.Timestamp(c["created_at_bar"]).to_pydatetime(),
            "invalidated_at_bar": pd.Timestamp(c["invalidated_at_bar"]).to_pydatetime() if c["invalidated_at_bar"] is not None else None,
        })
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--days", type=int, default=NESTED_WINDOW_DAYS)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol
    since = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=args.days)).strftime("%Y-%m-%d")

    print(f"Loading {symbol} HTF zones + raw OHLC since {since}...")
    htf_zones_by_tf = {tf: load_zones(symbol, tf, since) for tf in ("d1", "h6", "h4", "h1")}
    print(f"Root pool: " + ", ".join(f"{tf}={len(htf_zones_by_tf[tf])}" for tf in ("d1", "h6", "h4", "h1")))

    m15 = load("SELECT price_datetime, open_price, high_price, low_price, close_price FROM m15 ORDER BY price_datetime", RAW_DB[symbol])
    m15["price_datetime"] = pd.to_datetime(m15["price_datetime"])
    for c in ("open_price", "high_price", "low_price", "close_price"):
        m15[c] = m15[c].astype(float)
    m5 = load("SELECT price_datetime, open_price, high_price, low_price, close_price FROM m5 ORDER BY price_datetime", RAW_DB[symbol])
    m5["price_datetime"] = pd.to_datetime(m5["price_datetime"])
    for c in ("open_price", "high_price", "low_price", "close_price"):
        m5[c] = m5[c].astype(float)

    print("Drilling nested chains (fresh M15/M5 zone detection per root -- slow)...")
    chains = nze.build_nested_chains(symbol, htf_zones_by_tf, m15, m5)
    print(f"Chains found (LTF-terminated, deduped): {len(chains)}")

    if not args.no_write:
        n = persist_chains(symbol, chains)
        print(f"Upserted {n} chains into nested_zone_chains")


if __name__ == "__main__":
    main()
