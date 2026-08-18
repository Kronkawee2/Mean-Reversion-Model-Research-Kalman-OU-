"""
Resolves 'open' rows in composite_confluence_signals against real price
history as it accumulates -- reuses
analysis/backtester/structural_backtest_engine.simulate() UNMODIFIED (the
exact same walk-forward/ambiguous-bar-drilldown/conservative-SL-fallback
logic the baseline system's own backtest uses), judged against TP1/stop,
matching the hard R:R rule each signal was accepted under. No overlap
constraint applied -- every open signal is resolved independently,
regardless of whether another signal's position would still be "open" on a
real account; this table tracks the SIGNAL's own outcome, not a simulated
single-account equity curve (the user decides in real trading which
signals to actually take -- see user_action/user_note columns).

Run this on a schedule (e.g. daily, after the regular detection pipeline)
so exit_reason/r_outcome fill in as price actually plays out. Signals with
no resolution yet (price hasn't reached TP1 or stop) stay 'open' and are
simply re-checked next run -- no data is lost or re-computed unnecessarily,
since already-resolved rows are skipped entirely.

Usage:
    python scripts/detection/run_composite_confluence_resolution.py --symbol XAUUSD
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    open_signals = load("SELECT id, direction, confirmed_at_bar, entry_price, stop_price, tp1_price, tp1_rr "
                         "FROM composite_confluence_signals WHERE symbol=%s AND exit_reason='open'",
                         SILVER_DB[symbol], (symbol,))
    print(f"[{symbol}] {len(open_signals)} open signals to check")
    if open_signals.empty:
        return

    open_signals["confirmed_at_bar"] = pd.to_datetime(open_signals["confirmed_at_bar"])

    # Shape into the same columns structural_backtest_engine.simulate() expects.
    triggers = open_signals.rename(columns={"tp1_price": "target_price", "tp1_rr": "structural_rr"}).copy()
    triggers["symbol"] = symbol
    triggers["ltf_timeframe"] = "m15"
    triggers["mode"] = "composite"
    triggers["htf_zone_type"] = "order_block_bullish"  # unused by simulate() beyond pass-through
    triggers["htf_zone_top"] = triggers["entry_price"]
    triggers["htf_zone_bottom"] = triggers["entry_price"]
    for c in ("entry_price", "stop_price", "target_price", "structural_rr"):
        triggers[c] = triggers[c].astype(float)

    m15 = load("SELECT price_datetime, high_price, low_price FROM m15 WHERE price_datetime >= %s ORDER BY price_datetime",
               RAW_DB[symbol], (open_signals["confirmed_at_bar"].min(),))
    m15["price_datetime"] = pd.to_datetime(m15["price_datetime"])
    for c in ("high_price", "low_price"):
        m15[c] = m15[c].astype(float)
    m5 = load("SELECT price_datetime, high_price, low_price FROM m5 WHERE price_datetime >= %s ORDER BY price_datetime",
              RAW_DB[symbol], (open_signals["confirmed_at_bar"].min(),))
    m5["price_datetime"] = pd.to_datetime(m5["price_datetime"])
    for c in ("high_price", "low_price"):
        m5[c] = m5[c].astype(float)

    trades, _ = simulate(triggers, m15, m5)

    resolved = trades[trades["exit_reason"].isin(["win", "loss"])]
    print(f"[{symbol}] {len(resolved)}/{len(trades)} resolved this run "
          f"(win={int((resolved['exit_reason']=='win').sum())}, loss={int((resolved['exit_reason']=='loss').sum())}, "
          f"still open={int((trades['exit_reason']=='open_at_data_end').sum())})")

    if args.no_write or resolved.empty:
        return

    id_by_entry_time = dict(zip(open_signals["confirmed_at_bar"], open_signals["id"]))
    conn = _conn(SILVER_DB[symbol])
    sql = """
    UPDATE composite_confluence_signals
    SET exit_reason=%(exit_reason)s, exit_bar_datetime=%(exit_bar_datetime)s,
        resolution_method=%(resolution_method)s, r_outcome=%(r_outcome)s
    WHERE id=%(id)s
    """
    rows = []
    for _, row in resolved.iterrows():
        sig_id = id_by_entry_time.get(row["entry_bar_datetime"])
        if sig_id is None:
            continue
        rows.append({
            "id": sig_id, "exit_reason": row["exit_reason"],
            "exit_bar_datetime": row["exit_bar_datetime"],
            "resolution_method": row["resolution_method"],
            "r_outcome": float(row["r_outcome"]),
        })
    try:
        with conn.cursor() as cur:
            if rows:
                cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    print(f"[{symbol}] Updated {len(rows)} rows")


if __name__ == "__main__":
    main()
