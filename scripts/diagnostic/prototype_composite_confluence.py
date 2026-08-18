"""
Design-validation prototype for the proposed Composite Confluence Engine
(see docs/DECISIONS.md "Composite Confluence Engine: design + real-example
validation" entry). NOT the production engine -- this computes real
composite scores against real DB data for a recent slice of history to (a)
show the actual score distribution so a qualification threshold can be
picked from data, not guessed, and (b) print concrete real examples
(entry/stop/TP1..TPn/R:R) for review before anything is built for real.

Candidate anchor: an LTF (m15) touch of an active h1 SMC zone in its
expected reaction direction -- the SAME touch mechanism
analysis/strategies/ltf_trigger_engine.py already uses (formation-hour
exclusion included), collapsed to one event per contiguous touching run
(price sitting inside a zone for N bars is one touch, not N candidates).
Unlike ltf_trigger_engine.py, CHoCH is NOT required to generate a
candidate here -- it becomes one of six PARALLEL scoring inputs instead of
a sequential gate, which is the whole point of this redesign.

6 factors, each 0 or 1, reused from already-built engines/tables (nothing
re-detected except CHoCH and sweeps, which were never persisted to begin
with and are already computed live by ltf_trigger_engine.py the same way):
  1. sweep       liquidity_sweeps-equivalent (LiquiditySweepStateEngine on
                 the LTF series -- the persisted table only has h1, and
                 ltf_trigger_engine.py already computes this live on the
                 LTF series for the same reason), matching direction,
                 within TOUCH_WINDOW_M15_BARS of the touch.
  2. choch       SMCStructureEngine.detect_bos_choch() on the LTF series
                 (computed live -- not persisted anywhere, same as
                 ltf_trigger_engine.py and confluence_zone_engine.py both
                 already do), CHoCH in trigger direction within the same
                 window.
  3. zone_stack  >=2 ACTIVE h1 zones (any of order_block/fvg/swing) of the
                 trigger direction overlap current price at touch time --
                 the touched zone itself is always 1; this asks whether
                 ANOTHER zone also overlaps (real stacking).
  4. crt         htf_bias.crt_equilibrium_bias at the nearest h1 bar <=
                 touch matches direction (discount=bullish,
                 premium=bearish) -- reads the ALREADY-COMPUTED column, no
                 CRT recomputation.
  5. htf_bias    htf_bias.bias at the nearest h1 bar <= touch matches
                 direction exactly (neutral does not count).
  6. divergence  divergence_signals row, matching direction (any class,
                 any model), within DIVERGENCE_LOOKBACK_H1_BARS=20 h1 bars
                 of the touch (same constant htf_bias_engine.py uses).

Stop: PROVISIONAL, no method has been formally adopted yet (see
docs/DECISIONS.md "4 stop-calculation methods" entry -- status is
explicitly "awaiting the user's decision," production default is still
zone_far_edge). Uses stop_mode='nearest_structure' + widen_to_min_risk=True
("middle_ground") here because it had the best expectancy in all 4 real
backtest combinations tested so far -- flagged to the user as a provisional
choice for this design, not a retroactive adoption of that open decision.

Targets: ALL structural levels ahead of entry in the trade direction within
a capped search range (TARGET_MAX_ATR_MULTIPLE * ATR-14 -- a starting
bound, flagged unvalidated like every other constant in this project),
pooled from h1 SMC zones (opposing-direction near edge) and h4/h6/d1 CRT
equilibrium (if ahead of price), ranked by distance ascending -- nearest =
TP1, etc. Hard rule: TP1 R:R must be >= MIN_TP1_RR or the candidate is
discarded entirely.

Usage:
    python scripts/diagnostic/prototype_composite_confluence.py --symbol XAUUSD --days 120
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.smc_crt.structure import SMCStructureEngine  # noqa: E402
from analysis.smc_crt.liquidity_state import LiquiditySweepStateEngine  # noqa: E402
from analysis.strategies.ltf_trigger_engine import BULLISH_ZONE_TYPES, BEARISH_ZONE_TYPES  # noqa: E402
from analysis.strategies.structural_tp_engine import MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
# Display precision only -- R:R/qualification math always uses full-float
# entry/stop/target values, never these rounded strings. Matches ASSETS
# convention used elsewhere (dashboard/pages/3_LTF_Triggers.py).
PRICE_DECIMALS = {"XAUUSD": 2, "EURUSD": 5}

DIVERGENCE_LOOKBACK_H1_BARS = 20
TOUCH_WINDOW_M15_BARS = 20
TARGET_MAX_ATR_MULTIPLE = 10.0
MIN_TP1_RR = 3.0
SCORE_THRESHOLD = 4  # of 6 -- see docstring / DECISIONS.md for the empirical distribution behind this


def _conn(db):
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
                            database=db, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def load(sql, db, params=()):
    conn = _conn(db)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    conn.close()
    return pd.DataFrame(rows)


def zone_direction(zt):
    if zt in BULLISH_ZONE_TYPES:
        return "bullish"
    if zt in BEARISH_ZONE_TYPES:
        return "bearish"
    return None


def build_candidates(m15, h1_zones):
    bar_times = m15["price_datetime"].values
    lows = m15["low_price"].values
    highs = m15["high_price"].values
    candidates = []
    for _, zone in h1_zones.iterrows():
        direction = zone_direction(zone["zone_type"])
        if direction is None:
            continue
        created = np.datetime64(zone["created_at_bar"])
        invalidated = np.datetime64(zone["invalidated_at_bar"]) if pd.notnull(zone["invalidated_at_bar"]) else None
        active_mask = bar_times >= created
        if invalidated is not None:
            active_mask &= bar_times < invalidated
        formation_closed = created + np.timedelta64(1, "h")
        touch_mask = (active_mask & (bar_times >= formation_closed)
                      & (lows <= zone["zone_top"]) & (highs >= zone["zone_bottom"]))
        idxs = np.where(touch_mask)[0]
        if len(idxs) == 0:
            continue
        run_starts = idxs[np.where(np.diff(idxs, prepend=idxs[0] - 2) > 1)[0]]
        for i in run_starts:
            candidates.append({"touch_idx": i, "touch_time": m15["price_datetime"].iloc[i],
                                "direction": direction, "zone_type": zone["zone_type"],
                                "zone_top": zone["zone_top"], "zone_bottom": zone["zone_bottom"]})
    return pd.DataFrame(candidates).drop_duplicates(
        subset=["touch_time", "direction", "zone_type", "zone_top", "zone_bottom"])


def score_candidates(cand_df, sweeps, choch, h1_zones, htf_bias, divs):
    scores = []
    for _, c in cand_df.iterrows():
        t = c["touch_time"]
        direction = c["direction"]
        window_start = t - pd.Timedelta(minutes=15 * TOUCH_WINDOW_M15_BARS)

        f_sweep = int(((sweeps["direction"] == direction) & (sweeps["bar_datetime"] > window_start) & (sweeps["bar_datetime"] <= t)).any())
        f_choch_dir = "BULLISH_CHOCH" if direction == "bullish" else "BEARISH_CHOCH"
        f_choch = int(((choch["smc_structure_signal"] == f_choch_dir) & (choch["price_datetime"] > window_start) & (choch["price_datetime"] <= t)).any())

        same_types = BULLISH_ZONE_TYPES if direction == "bullish" else BEARISH_ZONE_TYPES
        overlapping = h1_zones[(h1_zones["zone_type"].isin(same_types))
                                & (h1_zones["created_at_bar"] <= t)
                                & (h1_zones["invalidated_at_bar"].isna() | (h1_zones["invalidated_at_bar"] > t))
                                & (h1_zones["zone_bottom"] <= c["zone_top"]) & (h1_zones["zone_top"] >= c["zone_bottom"])]
        f_zone_stack = int(len(overlapping) >= 2)

        hb = htf_bias[htf_bias["bar_datetime"] <= t]
        if not hb.empty:
            last_hb = hb.iloc[-1]
            f_crt = int(last_hb["crt_equilibrium_bias"] == ("discount" if direction == "bullish" else "premium"))
            f_bias = int(last_hb["bias"] == direction)
        else:
            f_crt = f_bias = 0

        div_window_start = t - pd.Timedelta(hours=DIVERGENCE_LOOKBACK_H1_BARS)
        f_div = int(((divs["direction"] == direction) & (divs["bar_datetime"] > div_window_start) & (divs["bar_datetime"] <= t)).any())

        score = f_sweep + f_choch + f_zone_stack + f_crt + f_bias + f_div
        scores.append({**c.to_dict(), "f_sweep": f_sweep, "f_choch": f_choch, "f_zone_stack": f_zone_stack,
                        "f_crt": f_crt, "f_bias": f_bias, "f_div": f_div, "score": score})
    return pd.DataFrame(scores)


def compute_stop_and_targets(qualified, m15, h1_zones, atr_by_bar, crt_eq, dec=2,
                              target_max_atr_multiple=TARGET_MAX_ATR_MULTIPLE, min_tp1_rr=MIN_TP1_RR,
                              stop_method="nearest_structure", mae_atr_multiple=None):
    """
    stop_method: 'nearest_structure' (default, the "middle_ground"-equivalent
        used throughout this design pass -- nearest same-direction zone's far
        edge, capped/floored by ATR) or 'mae_atr' (fixed entry -/+
        mae_atr_multiple * ATR-14, the best-R:R method from the earlier "4
        stop-calculation methods" comparison -- see docs/DECISIONS.md;
        requires mae_atr_multiple).
    """
    if stop_method == "mae_atr" and mae_atr_multiple is None:
        raise ValueError("mae_atr_multiple is required when stop_method='mae_atr'")

    m15_close_by_time = dict(zip(m15["price_datetime"], m15["close_price"]))
    results = []
    for _, c in qualified.iterrows():
        t = c["touch_time"]
        direction = c["direction"]
        entry = float(m15_close_by_time.get(t, np.nan))
        if np.isnan(entry):
            continue
        atr = atr_by_bar.get(pd.Timestamp(t).floor("h"))
        if atr is None:
            continue

        if stop_method == "mae_atr":
            risk = mae_atr_multiple * atr
            stop = entry - risk if direction == "bullish" else entry + risk
        else:
            same_types = BULLISH_ZONE_TYPES if direction == "bullish" else BEARISH_ZONE_TYPES
            same_causal = h1_zones[(h1_zones["zone_type"].isin(same_types))
                                   & (h1_zones["created_at_bar"] <= t)
                                   & (h1_zones["invalidated_at_bar"].isna() | (h1_zones["invalidated_at_bar"] > t))]
            if direction == "bullish":
                same_candidates = same_causal[same_causal["zone_bottom"] < entry]
                stop = float(same_candidates["zone_bottom"].max()) if not same_candidates.empty else float(c["zone_bottom"])
            else:
                same_candidates = same_causal[same_causal["zone_top"] > entry]
                stop = float(same_candidates["zone_top"].min()) if not same_candidates.empty else float(c["zone_top"])

            max_risk = MAX_STOP_ATR_MULTIPLE * atr
            risk = (entry - stop) if direction == "bullish" else (stop - entry)
            if risk > max_risk:
                risk = max_risk
                stop = entry - risk if direction == "bullish" else entry + risk

        min_risk = MIN_RISK_ATR_MULTIPLE * atr
        if risk <= 0:
            continue
        if risk < min_risk:
            risk = min_risk
            stop = entry - risk if direction == "bullish" else entry + risk

        opposing_types = BEARISH_ZONE_TYPES if direction == "bullish" else BULLISH_ZONE_TYPES
        opposing = h1_zones[(h1_zones["zone_type"].isin(opposing_types))
                            & (h1_zones["created_at_bar"] <= t)
                            & (h1_zones["invalidated_at_bar"].isna() | (h1_zones["invalidated_at_bar"] > t))]
        max_range = target_max_atr_multiple * atr
        levels = []
        for _, z in opposing.iterrows():
            near_edge = float(z["zone_bottom"]) if direction == "bullish" else float(z["zone_top"])
            dist = (near_edge - entry) if direction == "bullish" else (entry - near_edge)
            if 0 < dist <= max_range:
                levels.append((dist, near_edge, f"{z['zone_type']}"))

        eq_before = crt_eq[crt_eq["bar_datetime"] <= t]
        if not eq_before.empty:
            latest_eq_by_tf = eq_before.sort_values("bar_datetime").groupby("timeframe").tail(1)
            for _, e in latest_eq_by_tf.iterrows():
                eq_price = float(e["equilibrium_price"])
                dist = (eq_price - entry) if direction == "bullish" else (entry - eq_price)
                if 0 < dist <= max_range:
                    levels.append((dist, eq_price, f"crt_equilibrium_{e['timeframe']}"))

        if not levels:
            continue
        levels.sort(key=lambda x: x[0])
        dedup = []
        for lv in levels:
            if not dedup or abs(lv[0] - dedup[-1][0]) > 0.1 * atr:
                dedup.append(lv)
        levels = dedup

        tp1_dist, tp1_price, tp1_src = levels[0]
        tp1_rr = tp1_dist / risk
        if tp1_rr < min_tp1_rr:
            continue

        results.append({
            "touch_time": t, "direction": direction, "score": c["score"],
            "factors": {k: int(c[k]) for k in ("f_sweep", "f_choch", "f_zone_stack", "f_crt", "f_bias", "f_div")},
            "entry": entry, "stop": stop, "risk": risk,
            "targets": [(round(p, dec), src, round(dist / risk, 2)) for dist, p, src in levels[:5]],
            "tp1_rr": tp1_rr,
        })

    # Dedup at the RESULTS level, not just candidate level: distinct
    # overlapping zones (different boundaries, different created_at_bar --
    # genuinely different zone rows, not a data bug) can be touched at the
    # exact same bar and, once nearest_structure/targets are computed, land
    # on the IDENTICAL actionable trade (same entry/stop/direction) -- that
    # is one real signal, not N. Keep the highest-scoring copy (ties broken
    # by first-seen) when this happens.
    seen = {}
    for r in results:
        key = (r["touch_time"], r["direction"], round(r["entry"], dec), round(r["stop"], dec))
        if key not in seen or r["score"] > seen[key]["score"]:
            seen[key] = r
    return list(seen.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--days", type=int, default=120)
    args = parser.parse_args()
    symbol = args.symbol
    since = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=args.days)
    print(f"Window: {since} -> now  ({symbol})")

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

    print(f"Loaded: {len(m15)} m15 bars, {len(h1_zones)} h1 zones, {len(sweeps)} sweeps, "
          f"{len(htf_bias)} htf_bias rows, {len(divs)} divergence rows, {len(crt_eq)} CRT equilibrium rows")

    structure = SMCStructureEngine().detect_bos_choch(m15)
    choch = structure[structure["smc_structure_signal"].isin(["BULLISH_CHOCH", "BEARISH_CHOCH"])]

    cand_df = build_candidates(m15, h1_zones)
    print(f"\nCandidate touches (m15 touching an active h1 zone, collapsed to one per contiguous run): {len(cand_df)}")

    sdf = score_candidates(cand_df, sweeps, choch, h1_zones, htf_bias, divs)
    print("\nScore distribution (0-6):")
    print(sdf["score"].value_counts().sort_index().to_string())

    qualified = sdf[sdf["score"] >= SCORE_THRESHOLD].copy()
    print(f"\nCandidates scoring >= {SCORE_THRESHOLD}/6: {len(qualified)}")

    results = compute_stop_and_targets(qualified, m15, h1_zones, atr_by_bar, crt_eq, dec=PRICE_DECIMALS[symbol])
    print(f"Candidates scoring >= {SCORE_THRESHOLD} AND TP1 R:R >= {MIN_TP1_RR}: {len(results)}")

    results.sort(key=lambda r: -r["score"])
    print(f"\n{'='*90}\nQUALIFYING EXAMPLES\n{'='*90}")
    dec = PRICE_DECIMALS[symbol]
    for r in results:
        print(f"\n{r['touch_time']}  {r['direction'].upper()}  score={r['score']}/6  factors={r['factors']}")
        print(f"  entry={r['entry']:.{dec}f}  stop={r['stop']:.{dec}f}  risk={r['risk']:.{dec}f}")
        for i, (price, src, rr) in enumerate(r["targets"], start=1):
            print(f"  TP{i}: {price:.{dec}f}  ({src})  R:R={rr:.2f}")

    if results:
        print(f"\n{'='*90}\nFACTOR-PRESENCE BREAKDOWN across {len(results)} qualifying signals\n{'='*90}")
        for fname in ("f_sweep", "f_choch", "f_zone_stack", "f_crt", "f_bias", "f_div"):
            present = sum(r["factors"][fname] for r in results)
            print(f"  {fname:12s} present in {present}/{len(results)} ({present/len(results):.1%})")

        span_days = (m15["price_datetime"].max() - m15["price_datetime"].min()).days
        signals_per_day = len(results) / span_days if span_days else float("nan")
        annualized = signals_per_day * 365.25
        print(f"\n{len(results)} qualifying signals over {span_days} days -> "
              f"{signals_per_day:.3f}/day -> ~{annualized:.0f}/12mo annualized")
        print(f"(this project's MIN_TRADES_PER_12_MONTHS floor is 200; scaled to {span_days}d that's "
              f"~{200*span_days/365.25:.0f} trades required)")


if __name__ == "__main__":
    main()
