"""
Runs analysis/strategies/composite_confluence_engine.py against real data
and upserts qualifying signals into curated_<symbol>.composite_confluence_signals.
Non-qualifying candidates are never persisted (matches structural_tp_engine.py's
skip-not-weaken convention). Re-running is safe -- upsert on
(symbol, ltf_timeframe, direction, confirmed_at_bar), no duplicate rows.

Bounded by the shared 2-year rolling window (analysis/rolling_window.py) by
default, same as every other run_*.py detection script -- ongoing/live
signal generation only needs recent data. Pass --since to override (used
once, at adoption, to seed the table with the already-validated
full-history signal set rather than starting from an empty table).

Usage:
    python scripts/detection/run_composite_confluence_detection.py --symbol XAUUSD
    python scripts/detection/run_composite_confluence_detection.py --symbol XAUUSD --since 2022-05-24
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.smc_crt.structure import SMCStructureEngine  # noqa: E402
from analysis.smc_crt.liquidity_state import LiquiditySweepStateEngine  # noqa: E402
from analysis.strategies import composite_confluence_engine as cce  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}


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


def load_all(symbol, since):
    m15 = load("SELECT price_datetime, high_price, low_price, close_price FROM m15 WHERE price_datetime >= %s ORDER BY price_datetime",
                RAW_DB[symbol], (since,))
    m15["price_datetime"] = pd.to_datetime(m15["price_datetime"])
    for c in ("high_price", "low_price", "close_price"):
        m15[c] = m15[c].astype(float)

    h1_zones = load("SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar "
                     "FROM smc_signals WHERE symbol=%s AND timeframe='h1' AND created_at_bar >= %s",
                     SILVER_DB[symbol], (symbol, since))
    h1_zones["created_at_bar"] = pd.to_datetime(h1_zones["created_at_bar"])
    h1_zones["invalidated_at_bar"] = pd.to_datetime(h1_zones["invalidated_at_bar"])
    for c in ("zone_top", "zone_bottom"):
        h1_zones[c] = h1_zones[c].astype(float)

    # All 4 timeframes -- ONLY used for the zone_stack factor (see
    # composite_confluence_engine.ZONE_TIMEFRAME_WEIGHT). Candidate
    # generation/stop/target search remain h1-only, unchanged.
    all_tf_zones = load("SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar, timeframe "
                         "FROM smc_signals WHERE symbol=%s AND timeframe IN ('h1','h4','h6','d1') AND created_at_bar >= %s",
                         SILVER_DB[symbol], (symbol, since))
    all_tf_zones["created_at_bar"] = pd.to_datetime(all_tf_zones["created_at_bar"])
    all_tf_zones["invalidated_at_bar"] = pd.to_datetime(all_tf_zones["invalidated_at_bar"])
    for c in ("zone_top", "zone_bottom"):
        all_tf_zones[c] = all_tf_zones[c].astype(float)

    sweeps = LiquiditySweepStateEngine().detect_sweeps(m15, symbol=symbol, timeframe="m15")
    sweeps["bar_datetime"] = pd.to_datetime(sweeps["bar_datetime"])

    htf_bias = load("SELECT bar_datetime, bias, crt_equilibrium_bias FROM htf_bias "
                     "WHERE symbol=%s AND timeframe='h1' AND bar_datetime >= %s ORDER BY bar_datetime",
                     SILVER_DB[symbol], (symbol, since))
    htf_bias["bar_datetime"] = pd.to_datetime(htf_bias["bar_datetime"])

    divs = load("SELECT bar_datetime, direction FROM divergence_signals "
                "WHERE symbol=%s AND timeframe='h1' AND bar_datetime >= %s",
                SILVER_DB[symbol], (symbol, since))
    divs["bar_datetime"] = pd.to_datetime(divs["bar_datetime"])

    atr_by_bar = {r["bar_datetime"]: float(r["atr_14"]) for r in
                  load("SELECT bar_datetime, atr_14 FROM features WHERE symbol=%s AND timeframe='h1' AND bar_datetime >= %s",
                       SILVER_DB[symbol], (symbol, since)).to_dict("records")}

    crt_eq = load("SELECT timeframe, bar_datetime, equilibrium_price FROM crt_signals "
                  "WHERE symbol=%s AND signal_type='equilibrium' AND equilibrium_price IS NOT NULL",
                  SILVER_DB[symbol], (symbol,))
    crt_eq["bar_datetime"] = pd.to_datetime(crt_eq["bar_datetime"])
    crt_eq["equilibrium_price"] = crt_eq["equilibrium_price"].astype(float)

    structure = SMCStructureEngine().detect_bos_choch(m15)
    choch = structure[structure["smc_structure_signal"].isin(["BULLISH_CHOCH", "BEARISH_CHOCH"])]

    return m15, h1_zones, all_tf_zones, sweeps, choch, htf_bias, divs, atr_by_bar, crt_eq


def persist(symbol, ltf_timeframe, results):
    import json
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO composite_confluence_signals
        (symbol, ltf_timeframe, direction, confirmed_at_bar, score,
         f_sweep, f_choch, f_zone_stack, f_crt, f_bias, f_div,
         entry_price, stop_price, risk, targets, tp1_price, tp1_rr)
    VALUES
        (%(symbol)s, %(ltf_timeframe)s, %(direction)s, %(confirmed_at_bar)s, %(score)s,
         %(f_sweep)s, %(f_choch)s, %(f_zone_stack)s, %(f_crt)s, %(f_bias)s, %(f_div)s,
         %(entry_price)s, %(stop_price)s, %(risk)s, %(targets)s, %(tp1_price)s, %(tp1_rr)s)
    ON DUPLICATE KEY UPDATE
        score=VALUES(score), f_sweep=VALUES(f_sweep), f_choch=VALUES(f_choch),
        f_zone_stack=VALUES(f_zone_stack), f_crt=VALUES(f_crt), f_bias=VALUES(f_bias),
        f_div=VALUES(f_div), entry_price=VALUES(entry_price), stop_price=VALUES(stop_price),
        risk=VALUES(risk), targets=VALUES(targets), tp1_price=VALUES(tp1_price), tp1_rr=VALUES(tp1_rr)
    """
    rows = []
    for r in results:
        rows.append({
            "symbol": symbol, "ltf_timeframe": ltf_timeframe, "direction": r["direction"],
            "confirmed_at_bar": pd.Timestamp(r["touch_time"]).to_pydatetime(),
            "score": r["score"], **r["factors"],
            "entry_price": r["entry"], "stop_price": r["stop"], "risk": r["risk"],
            "targets": json.dumps([{"price": p, "source": src, "rr": rr} for p, src, rr in r["targets"]]),
            "tp1_price": r["tp1_price"], "tp1_rr": r["tp1_rr"],
        })
    try:
        with conn.cursor() as cur:
            if rows:
                cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--since", default=None, help="override the rolling-window start (YYYY-MM-DD); "
                                                        "used once at adoption to seed full history")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol
    since = args.since or rolling_window_start()

    print(f"Loading {symbol} data since {since}...")
    m15, h1_zones, all_tf_zones, sweeps, choch, htf_bias, divs, atr_by_bar, crt_eq = load_all(symbol, since)
    print(f"Loaded: {len(m15)} m15 bars, {len(h1_zones)} h1 zones, {len(sweeps)} sweeps, "
          f"{len(htf_bias)} htf_bias rows, {len(divs)} divergence rows, {len(crt_eq)} CRT equilibrium rows")

    cand_df = cce.build_candidates(m15, h1_zones)
    print(f"Candidate touches: {len(cand_df)}")
    sdf = cce.score_candidates(cand_df, sweeps, choch, h1_zones, htf_bias, divs, all_tf_zones=all_tf_zones)
    qualified = sdf[sdf["score"] >= cce.SCORE_THRESHOLD].copy() if not sdf.empty else sdf
    print(f"Candidates scoring >= {cce.SCORE_THRESHOLD}/6: {len(qualified)}")

    results = cce.compute_stop_and_targets(qualified, m15, h1_zones, atr_by_bar, crt_eq)
    print(f"Qualifying signals (TP1 R:R >= {cce.MIN_TP1_RR}): {len(results)}")

    if not args.no_write:
        n = persist(symbol, "m15", results)
        print(f"Upserted {n} signals into composite_confluence_signals")


if __name__ == "__main__":
    main()
