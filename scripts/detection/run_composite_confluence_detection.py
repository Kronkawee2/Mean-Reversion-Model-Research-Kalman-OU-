"""
Runs analysis/strategies/composite_confluence_engine.py against real data
and upserts scoring candidates into curated_<symbol>.composite_confluence_signals.
Persists down to cce.PERSIST_MIN_SCORE (2/5), not just the cce.SCORE_THRESHOLD
(3/5) production-qualifying floor -- the extra rows back the dashboard's
selectable ">=2/5, higher frequency lower quality" alternate view (see
docs/DECISIONS.md "threshold >=2/5 isolation test"); every unfiltered/default
read of this table (docs, resolution stats) still means score >= SCORE_THRESHOLD
when it says "qualifying". Candidates below PERSIST_MIN_SCORE are still never
persisted (matches structural_tp_engine.py's skip-not-weaken convention for
its own hard floor). Re-running is safe -- upsert on
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
from analysis.strategies import nested_zone_engine as nze  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

# Nested Zone Drilling replaced H1-touch as the production entry mechanism
# (see docs/DECISIONS.md -- consistent win-rate/expectancy advantage across
# three comparison runs). Bounded to a SHORTER window than the main rolling
# window: drilling runs fresh SMCZoneStateEngine detection per candidate
# root zone (M15/M5 zones were never persisted before this), which is too
# expensive to run across the full ~730-day rolling window on every regular
# pipeline pass. 180 days is the window the production decision was
# actually validated against.
NESTED_WINDOW_DAYS = 180

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
    m15 = load("SELECT price_datetime, open_price, high_price, low_price, close_price FROM m15 WHERE price_datetime >= %s ORDER BY price_datetime",
                RAW_DB[symbol], (since,))
    m15["price_datetime"] = pd.to_datetime(m15["price_datetime"])
    for c in ("open_price", "high_price", "low_price", "close_price"):
        m15[c] = m15[c].astype(float)

    h1_zones = load("SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar "
                     "FROM smc_signals WHERE symbol=%s AND timeframe='h1' AND created_at_bar >= %s",
                     SILVER_DB[symbol], (symbol, since))
    h1_zones["created_at_bar"] = pd.to_datetime(h1_zones["created_at_bar"])
    h1_zones["invalidated_at_bar"] = pd.to_datetime(h1_zones["invalidated_at_bar"])
    for c in ("zone_top", "zone_bottom"):
        h1_zones[c] = h1_zones[c].astype(float)

    # All 4 timeframes -- used for the zone_stack factor (see
    # composite_confluence_engine.ZONE_TIMEFRAME_WEIGHT) AND as the root
    # pool for Nested Zone Drilling (see main(), htf_zones_by_tf). `state`
    # is required here now: Nested Zone Drilling's root/intermediate-level
    # filtering excludes 'invalidated' zones, so it must be fetched, not
    # defaulted -- treating invalidated zones as eligible would silently
    # drill through dead structure.
    all_tf_zones = load("SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar, timeframe, state "
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


def persist(symbol, ltf_timeframe, results, chain_by_bounds=None):
    import json
    conn = _conn(SILVER_DB[symbol])
    sql = """
    INSERT INTO composite_confluence_signals
        (symbol, ltf_timeframe, direction, confirmed_at_bar, score,
         f_sweep, f_choch, f_zone_stack, f_crt, f_bias, f_div,
         entry_price, stop_price, risk, targets, tp1_price, tp1_rr,
         entry_mechanism, zone_chain)
    VALUES
        (%(symbol)s, %(ltf_timeframe)s, %(direction)s, %(confirmed_at_bar)s, %(score)s,
         %(f_sweep)s, %(f_choch)s, %(f_zone_stack)s, %(f_crt)s, %(f_bias)s, %(f_div)s,
         %(entry_price)s, %(stop_price)s, %(risk)s, %(targets)s, %(tp1_price)s, %(tp1_rr)s,
         %(entry_mechanism)s, %(zone_chain)s)
    ON DUPLICATE KEY UPDATE
        score=VALUES(score), f_sweep=VALUES(f_sweep), f_choch=VALUES(f_choch),
        f_zone_stack=VALUES(f_zone_stack), f_crt=VALUES(f_crt), f_bias=VALUES(f_bias),
        f_div=VALUES(f_div), entry_price=VALUES(entry_price), stop_price=VALUES(stop_price),
        risk=VALUES(risk), targets=VALUES(targets), tp1_price=VALUES(tp1_price), tp1_rr=VALUES(tp1_rr),
        entry_mechanism=VALUES(entry_mechanism), zone_chain=VALUES(zone_chain)
    """
    chain_by_bounds = chain_by_bounds or {}
    rows = []
    for r in results:
        key = (round(r["zone_top"], 5), round(r["zone_bottom"], 5)) if "zone_top" in r else None
        chain = chain_by_bounds.get(key)
        rows.append({
            "symbol": symbol, "ltf_timeframe": ltf_timeframe, "direction": r["direction"],
            "confirmed_at_bar": pd.Timestamp(r["touch_time"]).to_pydatetime(),
            "score": r["score"], **r["factors"],
            "entry_price": r["entry"], "stop_price": r["stop"], "risk": r["risk"],
            "targets": json.dumps([{"price": p, "source": src, "rr": rr} for p, src, rr in r["targets"]]),
            "tp1_price": r["tp1_price"], "tp1_rr": r["tp1_rr"],
            "entry_mechanism": "nested_chain" if chain is not None else "h1_touch",
            "zone_chain": json.dumps(chain) if chain is not None else None,
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

    # Nested Zone Drilling roots -- bounded to NESTED_WINDOW_DAYS (shorter
    # than `since`, see module docstring). all_tf_zones already covers the
    # full `since` window and is reused unchanged for zone_stack scoring.
    nested_since = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=NESTED_WINDOW_DAYS)).strftime("%Y-%m-%d")
    htf_zones_by_tf = {
        tf: all_tf_zones[(all_tf_zones["timeframe"] == tf) & (all_tf_zones["created_at_bar"] >= nested_since)].copy()
        for tf in ("d1", "h6", "h4", "h1")
    }
    m5 = load("SELECT price_datetime, open_price, high_price, low_price, close_price FROM m5 WHERE price_datetime >= %s ORDER BY price_datetime",
              RAW_DB[symbol], (nested_since,))
    m5["price_datetime"] = pd.to_datetime(m5["price_datetime"])
    for c in ("open_price", "high_price", "low_price", "close_price"):
        m5[c] = m5[c].astype(float)

    # Root prioritization -- adopted production behavior (see docs/DECISIONS.md):
    # only drill roots with 2+ of the 5 composite factors present nearby
    # (tight, touch-time-matching windows -- TOUCH_WINDOW_M15_BARS for
    # sweep/CHoCH, DIVERGENCE_LOOKBACK_H1_BARS for divergence, snapshots for
    # bias/zone_stack), instead of every active/mitigated zone. Real compute
    # savings (-7% to -23% chains drilled) with no meaningful quality loss
    # in the validated comparison. Intermediate-level nesting search still
    # uses the FULL htf_zones_by_tf -- only which zones become ROOTS is
    # prioritized, not what a chain can nest through once started.
    root_zones_by_tf = nze.filter_roots_near_composite_factors(htf_zones_by_tf, sweeps, choch, all_tf_zones, htf_bias, divs)
    for tf in ("d1", "h6", "h4", "h1"):
        before, after = len(htf_zones_by_tf[tf]), len(root_zones_by_tf[tf])
        print(f"  Root pool {tf}: {before} -> {after} ({after/before*100 if before else 0:.1f}% kept, composite-factor-prioritized)")

    print(f"Drilling nested chains since {nested_since} (fresh M15/M5 zone detection per root -- slow)...")
    chains = nze.build_nested_chains(symbol, htf_zones_by_tf, m15, m5, root_zones_by_tf=root_zones_by_tf)
    print(f"Chains found (LTF-terminated, deduped): {len(chains)}")
    terminal_zones = pd.DataFrame([{
        "zone_type": c["zone_type"], "zone_top": c["zone_top"], "zone_bottom": c["zone_bottom"],
        "created_at_bar": c["created_at_bar"], "invalidated_at_bar": c["invalidated_at_bar"],
        "timeframe": c["terminal_timeframe"],
    } for c in chains]) if chains else pd.DataFrame(
        columns=["zone_type", "zone_top", "zone_bottom", "created_at_bar", "invalidated_at_bar", "timeframe"])
    chain_by_bounds = {(round(c["zone_top"], 5), round(c["zone_bottom"], 5)): c["chain"] for c in chains}

    cand_df = cce.build_candidates(m15, terminal_zones)
    print(f"Candidate touches: {len(cand_df)}")
    sdf = cce.score_candidates(cand_df, sweeps, choch, h1_zones, htf_bias, divs, all_tf_zones=all_tf_zones)

    # Persist down to PERSIST_MIN_SCORE (2/5), not just the SCORE_THRESHOLD
    # (3/5) production-qualifying floor -- the dashboard's ">=2/5, higher
    # frequency lower quality" toggle (see docs/DECISIONS.md "threshold
    # >=2/5 isolation test") reads its rows from this same table, filtered
    # by the stored `score` column at display time, not a separate pipeline
    # run. SCORE_THRESHOLD remains what "qualifying" means for every
    # unfiltered/default view (this print, docs, resolution stats).
    persist_pool = sdf[sdf["score"] >= cce.PERSIST_MIN_SCORE].copy() if not sdf.empty else sdf
    qualified_count = int((persist_pool["score"] >= cce.SCORE_THRESHOLD).sum()) if not persist_pool.empty else 0
    print(f"Candidates scoring >= {cce.SCORE_THRESHOLD}/5 (production default): {qualified_count}")
    print(f"Candidates scoring >= {cce.PERSIST_MIN_SCORE}/5 (persisted, incl. dashboard alt-threshold rows): {len(persist_pool)}")

    # Stop/target search also uses terminal_zones (not h1_zones) -- this is
    # the validated mechanism (see docs/DECISIONS.md): searching among the
    # tight LTF chain terminals for the stop reference is what delivers the
    # "smallest possible SL" the design was built for. Falling back to
    # coarse H1 zones here would silently widen every stop back out and
    # defeat the point of drilling down in the first place.
    results = cce.compute_stop_and_targets(persist_pool, m15, terminal_zones, atr_by_bar, crt_eq)
    print(f"Persisted candidates also clearing TP1 R:R >= {cce.MIN_TP1_RR}: {len(results)}")

    if not args.no_write:
        n = persist(symbol, "m15", results, chain_by_bounds=chain_by_bounds)
        print(f"Upserted {n} signals into composite_confluence_signals")


if __name__ == "__main__":
    main()
