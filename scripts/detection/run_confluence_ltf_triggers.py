"""
Runs the Confluence LTF Trigger pass: confirms LTF (m15) entries against
h4 confluence zones (mode_a_2factor and mode_b_3factor), for both LTF
confirmation modes (choch_only/choch_sweep) -- a 2x2 variant comparison,
same "build both, compare with real data, no forced default" pattern
used everywhere else in this project.

Target selection -- TWO variants computed and persisted per entry
(target_zone_source column), not one: 'smc_signals' (original behavior,
nearest opposing single-factor h1 zone) and 'confluence_zone' (nearest
opposing confluence zone of the SAME confluence_mode as the entry). This
is the confluence-aware target-selection test from docs/DECISIONS.md --
the backtest found confluence-sourced ENTRIES alone don't beat the
baseline (win rate holds, reward size doesn't), so this tests whether
sourcing the TARGET from confluence zones too closes that gap, on the
exact same entries, isolating the one variable. structural_tp_engine.py
itself is still unmodified either way -- only which htf_zones frame gets
passed in as the opposing-zone candidate pool changes, via
analysis/strategies/confluence_ltf_trigger.py's build_confluence_zone_frame()
reused for the target side (same proxy zone_type trick as the entry side,
full range -- see that function's docstring).

See docs/DECISIONS.md for the full design (approved after a real-data
walkthrough of 3 concrete confluence zones).

Usage:
    python scripts/detection/run_confluence_ltf_triggers.py --symbol XAUUSD
    python scripts/detection/run_confluence_ltf_triggers.py --symbol XAUUSD --confluence-mode mode_a_2factor --ltf-mode choch_only --no-write
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.confluence_ltf_trigger import (  # noqa: E402
    compute_confluence_triggers, build_confluence_zone_frame,
)
from analysis.strategies.ltf_trigger_engine import MODES as LTF_MODES  # noqa: E402
from analysis.strategies.structural_tp_engine import compute_structural_targets  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
CONFLUENCE_MODES = ("mode_a_2factor", "mode_b_3factor")
CONFLUENCE_HTF_TIMEFRAME = "h4"  # scope this pass -- see module docstring

# build_confluence_zone_frame()'s proxy zone_type, un-proxied back to a
# real, honest label for the persisted opposing_zone_type column -- this
# opposing zone IS a confluence zone, not an actual swing_support/
# swing_resistance pattern; mode doesn't need encoding here since
# opposing_zone_type isn't part of any unique key (unlike htf_zone_type).
OPPOSING_PROXY_TO_CONFLUENCE_TYPE = {"swing_support": "confluence_bullish", "swing_resistance": "confluence_bearish"}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_ltf_bars(symbol: str, ltf_timeframe: str) -> pd.DataFrame:
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, high_price, low_price, close_price FROM `{ltf_timeframe}` "
                f"WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_confluence_zones(symbol: str, confluence_mode: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, mode, direction, zone_full_top, zone_full_bottom, zone_core_top, zone_core_bottom, "
                "last_factor_at_bar, status, resolved_at_bar FROM confluence_zones "
                "WHERE symbol=%s AND timeframe=%s AND mode=%s",
                (symbol, CONFLUENCE_HTF_TIMEFRAME, confluence_mode),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_smc_opposing_zones(symbol: str) -> pd.DataFrame:
    """Opposing-zone reference for structural TP stays smc_signals h1
    (unchanged) -- the approved design didn't touch target logic."""
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar "
                "FROM smc_signals WHERE symbol=%s AND timeframe='h1' AND created_at_bar >= %s",
                (symbol, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_h1_atr(symbol: str) -> dict:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_datetime, atr_14 FROM features WHERE symbol=%s AND timeframe='h1' AND bar_datetime >= %s",
                (symbol, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {r["bar_datetime"]: float(r["atr_14"]) for r in rows}


def upsert_triggers(symbol: str, targets: pd.DataFrame) -> int:
    if targets.empty:
        return 0
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO ltf_trigger_signals
        (symbol, ltf_timeframe, mode, direction, htf_zone_type, htf_zone_top, htf_zone_bottom,
         htf_zone_created_at_bar, zone_source, confluence_zone_id, confluence_mode, zone_range_used,
         target_zone_source, touch_bar_datetime, choch_bar_datetime, sweep_bar_datetime, sweep_type,
         confirmed_at_bar, entry_price, stop_price, opposing_zone_type, opposing_zone_top, opposing_zone_bottom,
         target_price, structural_rr, target_status)
    VALUES
        (%(symbol)s, %(ltf_timeframe)s, %(mode)s, %(direction)s, %(htf_zone_type)s, %(htf_zone_top)s,
         %(htf_zone_bottom)s, %(htf_zone_created_at_bar)s, %(zone_source)s, %(confluence_zone_id)s,
         %(confluence_mode)s, %(zone_range_used)s, %(target_zone_source)s, %(touch_bar_datetime)s,
         %(choch_bar_datetime)s, %(sweep_bar_datetime)s, %(sweep_type)s, %(confirmed_at_bar)s, %(entry_price)s,
         %(stop_price)s, %(opposing_zone_type)s, %(opposing_zone_top)s, %(opposing_zone_bottom)s,
         %(target_price)s, %(structural_rr)s, %(target_status)s)
    ON DUPLICATE KEY UPDATE
        direction = VALUES(direction), sweep_bar_datetime = VALUES(sweep_bar_datetime),
        sweep_type = VALUES(sweep_type), confirmed_at_bar = VALUES(confirmed_at_bar),
        zone_range_used = VALUES(zone_range_used), entry_price = VALUES(entry_price),
        stop_price = VALUES(stop_price), opposing_zone_type = VALUES(opposing_zone_type),
        opposing_zone_top = VALUES(opposing_zone_top), opposing_zone_bottom = VALUES(opposing_zone_bottom),
        target_price = VALUES(target_price), structural_rr = VALUES(structural_rr),
        target_status = VALUES(target_status)
    """
    rows = targets.to_dict("records")
    for row in rows:
        for key, val in row.items():
            if pd.isna(val):
                row[key] = None
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def print_report(confluence_mode: str, ltf_mode: str, targets: pd.DataFrame, target_zone_source: str = "smc_signals"):
    label = f"{confluence_mode}/{ltf_mode}/target={target_zone_source}"
    print(f"\n[{label}] Total triggers: {len(targets)}")
    if targets.empty:
        return
    print(targets["zone_range_used"].value_counts().to_string())
    print(targets["target_status"].value_counts().to_string())

    structural = targets[targets["target_status"] == "structural"]
    if structural.empty:
        return
    rr = structural["structural_rr"].astype(float)
    print(f"\n[{label}] structural_rr distribution (n={len(rr)}):")
    print(rr.describe(percentiles=[.05, .25, .5, .75, .95]).to_string())

    print(f"\n[{label}] 2 example triggers:")
    for _, row in structural.tail(2).iterrows():
        print(f"  confirmed={row['confirmed_at_bar']}  entry={row['entry_price']:.2f}  "
              f"stop={row['stop_price']:.2f}  target={row['target_price']:.2f}  rr={row['structural_rr']:.3f}  "
              f"range_used={row['zone_range_used']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--confluence-mode", default="both", choices=list(CONFLUENCE_MODES) + ["both"])
    parser.add_argument("--ltf-mode", default="both", choices=list(LTF_MODES) + ["both"])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    ltf_bars = load_ltf_bars(symbol, "m15")
    print(f"Loaded {len(ltf_bars)} m15 bars for {symbol}: "
          f"{ltf_bars['price_datetime'].min()} -> {ltf_bars['price_datetime'].max()}")
    opposing_zones = load_smc_opposing_zones(symbol)
    print(f"Loaded {len(opposing_zones)} h1 SMC zones for opposing-zone lookup")
    atr_by_h1_bar = load_h1_atr(symbol)
    print(f"Loaded {len(atr_by_h1_bar)} h1 ATR-14 values")

    confluence_modes = list(CONFLUENCE_MODES) if args.confluence_mode == "both" else [args.confluence_mode]
    ltf_modes = list(LTF_MODES) if args.ltf_mode == "both" else [args.ltf_mode]

    for confluence_mode in confluence_modes:
        zones = load_confluence_zones(symbol, confluence_mode)
        print(f"\n{confluence_mode}: {len(zones)} confluence zones ({CONFLUENCE_HTF_TIMEFRAME})")
        if zones.empty:
            continue

        for ltf_mode in ltf_modes:
            triggers = compute_confluence_triggers(
                ltf_bars, zones, symbol=symbol, ltf_timeframe="m15", mode=ltf_mode,
            )
            if triggers.empty:
                print(f"[{confluence_mode}/{ltf_mode}] No triggers found.")
                continue

            triggers["atr_14"] = triggers["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)

            # Same entries, two target sources -- the controlled A/B this
            # pass needed. 'smc_signals' is the original opposing-zone
            # search (unchanged); 'confluence_zone' reuses the SAME
            # confluence zone set this entry came from (same mode) as the
            # opposing-wall candidate pool instead.
            confluence_opposing_zones = build_confluence_zone_frame(zones)

            for target_zone_source, opp_zones in (
                ("smc_signals", opposing_zones),
                ("confluence_zone", confluence_opposing_zones),
            ):
                targets = compute_structural_targets(triggers, opp_zones)
                targets["target_zone_source"] = target_zone_source
                if target_zone_source == "confluence_zone":
                    targets["opposing_zone_type"] = targets["opposing_zone_type"].map(OPPOSING_PROXY_TO_CONFLUENCE_TYPE)

                print_report(confluence_mode, ltf_mode, targets, target_zone_source)

                if not args.no_write:
                    n = upsert_triggers(symbol, targets)
                    print(f"[{confluence_mode}/{ltf_mode}/target={target_zone_source}] Upserted {n} trigger rows")


if __name__ == "__main__":
    main()
