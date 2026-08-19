"""
Composite Confluence Engine -- ADOPTED as the production signal source (see
docs/DECISIONS.md "Composite Confluence Engine" entries), despite not
clearing this project's own statistical floor at adoption time. Reasoning
recorded in the log: the R:R this engine produces (median ~2.5+) is what
the user actually trades; the original baseline's higher win rate/larger
sample came with a median R:R of ~0.28, which isn't a tradeable profile
regardless of its statistical maturity. The track record is intended to
accumulate through real, logged usage (composite_confluence_signals table)
rather than through another historical backfill.

This module ports the validated logic from
scripts/diagnostic/prototype_composite_confluence.py (kept, unmodified, as
the reusable revalidation/research tool) into a clean, importable engine
for the production detection/resolution scripts. No detection primitive is
reimplemented -- every factor reuses an existing engine or table exactly as
the design-validation phase established.

DESIGN, UNCHANGED FROM VALIDATION (see docs/DECISIONS.md for the full
reasoning and real-data evidence behind each choice):

Candidate anchor: an LTF (m15) touch of an active h1 SMC zone in its
expected reaction direction (analysis/strategies/ltf_trigger_engine.py's
own touch mechanism, minus its CHoCH gate), collapsed to one event per
contiguous touching run.

CRT DROPPED FROM SCORING (see docs/DECISIONS.md "SMC + Divergence adopted,
CRT removed"): isolation testing showed CRT was not the rejection
bottleneck (missing in ~61-63% of rejected candidates, mid-pack vs
htf_bias's ~97% and choch's ~83-85%) and a CRT-required gate performed
worse than every other tested variant, including slightly negative
expectancy on EURUSD (-0.126R). The SMC+Divergence variant (no CRT) beat
SMC-only on every metric in both symbols (sample size, win rate on XAUUSD,
expectancy on both) and was adopted as production. f_crt/crt_eq plumbing
is left in place (harmless, still loaded) but no longer contributes to the
score -- kept rather than ripped out in case a future test wants it back.

5 factors, each contributing 1 point if present (equal-weight binary,
confirmed to stay this way after the zone_stack-as-gate test showed
negligible difference from treating it as a scored vote):
  1. sweep       LiquiditySweepStateEngine on the LTF series.
  2. choch       SMCStructureEngine.detect_bos_choch() on the LTF series.
  3. zone_stack  >=2 weighted-sum active same-direction zones (any of
                 h1/h4/h6/d1) overlap current price -- see
                 ZONE_TIMEFRAME_WEIGHT.
  4. htf_bias    htf_bias.bias matches direction exactly.
  5. divergence  any divergence_signals row (any class/model) matching
                 direction within DIVERGENCE_LOOKBACK_H1_BARS.

Stop: 'nearest_structure' -- the nearest same-direction zone's far edge
(not necessarily the touched zone itself), ATR-floored/capped exactly as
structural_tp_engine.py's existing MIN/MAX_STOP_ATR_MULTIPLE bounds. Chosen
over the MAE-based alternative because that alternative's survivorship
bias (MAE computed from winning trades only) was never fixed -- flagged
explicitly, not silently avoided.

Targets: ALL structural levels ahead (h1 zones + h4/h6/d1 CRT equilibrium)
within TARGET_MAX_ATR_MULTIPLE, ranked by distance -- confirmed via a full
range sweep (10x-100x ATR) that widening this has NO effect on qualifying
count, so it is not a tunable lever in practice, just a safety bound.

PRODUCTION THRESHOLDS (last tested combination before adoption):
  SCORE_THRESHOLD = 3  (of 5 -- CRT dropped; closest achievable proportion
                        to the original 4/6, same methodology used for the
                        earlier SMC-only isolation test's 3/4)
  MIN_TP1_RR = 2.0     (lowered from the originally-tested 3.0 specifically
                        because the resulting R:R profile -- median ~2.5+ --
                        is what motivated adoption; see docs/DECISIONS.md)
Still does not clear this project's own statistical floor as of the
CRT-drop (XAUUSD ~38% of floor, EURUSD ~57% of floor, full available
history) -- closer than the original 6-factor config (~27%/42%) but still
short. Known, accepted, and explicitly documented gap, not an oversight.
"""

import numpy as np
import pandas as pd

from analysis.smc_crt.structure import SMCStructureEngine
from analysis.smc_crt.liquidity_state import LiquiditySweepStateEngine
from analysis.strategies.ltf_trigger_engine import BULLISH_ZONE_TYPES, BEARISH_ZONE_TYPES
from analysis.strategies.structural_tp_engine import MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE

DIVERGENCE_LOOKBACK_H1_BARS = 20
TOUCH_WINDOW_M15_BARS = 20
TARGET_MAX_ATR_MULTIPLE = 10.0

# Timeframe weighting for the zone_stack factor (see docs/DECISIONS.md --
# this was a real gap, not a design choice: zone_stack originally only
# ever loaded/considered h1 zones, so h4/h6/d1 structure was invisible to
# the composite score entirely, not just equally-weighted. Fixed to
# reflect the original intent (D1 > H6 > H4 > H1, "get all timeframes to
# cooperate") using the plain ordinal rank of the 4 timeframes actually
# detected elsewhere in this project (SMC zones run on exactly these 4,
# see run_smc_zone_detection.py) -- no new tunable constant invented
# beyond that ordering. f_zone_stack=1 if the WEIGHTED SUM of overlapping
# same-direction zones (any of the 4 timeframes) is >= 2 -- this exactly
# reproduces the original h1-only rule when every contributing zone is h1
# (weight 1, so >=2 means >=2 zones, unchanged), while now also letting a
# single higher-timeframe zone satisfy it alone (a lone D1 zone, weight 4,
# already clears >=2) -- "highest timeframe = most weight" applied
# directly to the existing threshold rather than adding a second one.
ZONE_TIMEFRAME_WEIGHT = {"d1": 4, "h6": 3, "h4": 2, "h1": 1}

SCORE_THRESHOLD = 3
MIN_TP1_RR = 2.0

FACTOR_COLUMNS = ("f_sweep", "f_choch", "f_zone_stack", "f_crt", "f_bias", "f_div")


def _zone_direction(zone_type: str):
    if zone_type in BULLISH_ZONE_TYPES:
        return "bullish"
    if zone_type in BEARISH_ZONE_TYPES:
        return "bearish"
    return None


# Formation-close gate: a zone only counts a touch once its OWN formation
# bar has fully closed -- one bar of the zone's own timeframe, not a fixed
# constant. The original (and still default) value, 1 hour, is exactly one
# H1 bar -- it was never really "wait an hour," it was "wait for the
# formation bar to close," which happened to be 1h because every zone
# build_candidates() saw was H1. Nested Zone Drilling's terminal zones are
# M15/M5, which routinely mitigate/invalidate inside an hour -- reusing the
# H1-sized gate against them silently killed ~95% of real touches before
# they could ever register (40/34 chains found, only 1/2 became qualifying
# signals in the first side-by-side comparison; see docs/DECISIONS.md).
# Selected via an optional per-zone 'timeframe' column so existing H1
# callers (who never pass this column) are completely unaffected --
# zero behavior change to the production H1-touch path.
FORMATION_GATE_BY_TIMEFRAME = {
    "h1": np.timedelta64(1, "h"),
    "m15": np.timedelta64(15, "m"),
    "m5": np.timedelta64(5, "m"),
}
DEFAULT_FORMATION_GATE = np.timedelta64(1, "h")


def build_candidates(m15: pd.DataFrame, h1_zones: pd.DataFrame) -> pd.DataFrame:
    """m15: price_datetime, high_price, low_price, close_price (raw, sorted ascending).
    h1_zones: zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar
    (curated.smc_signals, timeframe='h1'). An optional 'timeframe' column
    selects the formation-close gate per-zone via FORMATION_GATE_BY_TIMEFRAME
    (defaults to the original 1h/H1 behavior when absent). Returns one row
    per contiguous touching run (a real single touch event, not one row per
    bar)."""
    bar_times = m15["price_datetime"].values
    lows = m15["low_price"].values
    highs = m15["high_price"].values
    candidates = []
    for _, zone in h1_zones.iterrows():
        direction = _zone_direction(zone["zone_type"])
        if direction is None:
            continue
        created = np.datetime64(zone["created_at_bar"])
        invalidated = np.datetime64(zone["invalidated_at_bar"]) if pd.notnull(zone["invalidated_at_bar"]) else None
        active_mask = bar_times >= created
        if invalidated is not None:
            active_mask &= bar_times < invalidated
        zone_tf = zone["timeframe"] if "timeframe" in zone.index else None
        gate = FORMATION_GATE_BY_TIMEFRAME.get(zone_tf, DEFAULT_FORMATION_GATE)
        formation_closed = created + gate
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
    if not candidates:
        return pd.DataFrame(columns=["touch_idx", "touch_time", "direction", "zone_type", "zone_top", "zone_bottom"])
    return pd.DataFrame(candidates).drop_duplicates(
        subset=["touch_time", "direction", "zone_type", "zone_top", "zone_bottom"])


def score_candidates(cand_df: pd.DataFrame, sweeps: pd.DataFrame, choch: pd.DataFrame,
                      h1_zones: pd.DataFrame, htf_bias: pd.DataFrame, divs: pd.DataFrame,
                      all_tf_zones: pd.DataFrame = None, include_bos: bool = False) -> pd.DataFrame:
    """sweeps: LiquiditySweepStateEngine.detect_sweeps() output on the LTF
    series. choch: SMCStructureEngine.detect_bos_choch() output. By default
    (include_bos=False, current production behavior) the caller is expected
    to have already filtered this to BULLISH_CHOCH/BEARISH_CHOCH rows only
    -- BOS rows would simply never match and contribute nothing. Pass
    include_bos=True (with the FULL, unfiltered detect_bos_choch() output,
    BOS rows included) to broaden f_choch to count either CHoCH OR BOS --
    see docs/DECISIONS.md for why BOS was originally dropped (an
    unintentional gap, not a deliberate choice: detect_bos_choch() was
    always called for both, only CHoCH rows were kept before reaching this
    function) and the before/after comparison this flag exists to run.
    htf_bias: bar_datetime, bias, crt_equilibrium_bias (curated.htf_bias,
    timeframe='h1'). divs: bar_datetime, direction
    (curated.divergence_signals, timeframe='h1'). all_tf_zones: zone_type,
    zone_top, zone_bottom, created_at_bar, invalidated_at_bar, timeframe --
    smc_signals across all 4 timeframes (h1/h4/h6/d1), used ONLY for the
    zone_stack factor (see ZONE_TIMEFRAME_WEIGHT). Falls back to h1_zones
    (weight 1 each, the original behavior) if not provided, for backward
    compatibility."""
    if cand_df.empty:
        return cand_df.assign(**{c: pd.Series(dtype=int) for c in FACTOR_COLUMNS}, score=pd.Series(dtype=int))

    if all_tf_zones is None:
        all_tf_zones = h1_zones.assign(timeframe="h1")

    scores = []
    for _, c in cand_df.iterrows():
        t = c["touch_time"]
        direction = c["direction"]
        window_start = t - pd.Timedelta(minutes=15 * TOUCH_WINDOW_M15_BARS)

        f_sweep = int(((sweeps["direction"] == direction) & (sweeps["bar_datetime"] > window_start) & (sweeps["bar_datetime"] <= t)).any())
        if include_bos:
            choch_dirs = (["BULLISH_CHOCH", "BULLISH_BOS"] if direction == "bullish"
                           else ["BEARISH_CHOCH", "BEARISH_BOS"])
        else:
            choch_dirs = ["BULLISH_CHOCH"] if direction == "bullish" else ["BEARISH_CHOCH"]
        f_choch = int(((choch["smc_structure_signal"].isin(choch_dirs)) & (choch["price_datetime"] > window_start) & (choch["price_datetime"] <= t)).any())

        same_types = BULLISH_ZONE_TYPES if direction == "bullish" else BEARISH_ZONE_TYPES
        overlapping = all_tf_zones[(all_tf_zones["zone_type"].isin(same_types))
                                & (all_tf_zones["created_at_bar"] <= t)
                                & (all_tf_zones["invalidated_at_bar"].isna() | (all_tf_zones["invalidated_at_bar"] > t))
                                & (all_tf_zones["zone_bottom"] <= c["zone_top"]) & (all_tf_zones["zone_top"] >= c["zone_bottom"])]
        weighted_sum = overlapping["timeframe"].map(ZONE_TIMEFRAME_WEIGHT).fillna(1).sum()
        f_zone_stack = int(weighted_sum >= 2)

        hb = htf_bias[htf_bias["bar_datetime"] <= t]
        if not hb.empty:
            last_hb = hb.iloc[-1]
            f_crt = int(last_hb["crt_equilibrium_bias"] == ("discount" if direction == "bullish" else "premium"))
            f_bias = int(last_hb["bias"] == direction)
        else:
            f_crt = f_bias = 0

        div_window_start = t - pd.Timedelta(hours=DIVERGENCE_LOOKBACK_H1_BARS)
        f_div = int(((divs["direction"] == direction) & (divs["bar_datetime"] > div_window_start) & (divs["bar_datetime"] <= t)).any())

        # f_crt is computed and kept as a column (see module docstring --
        # plumbing left in place) but no longer contributes to the score:
        # CRT dropped from production scoring after isolation testing
        # showed it wasn't the rejection bottleneck and a CRT-required gate
        # underperformed every other tested variant.
        score = f_sweep + f_choch + f_zone_stack + f_bias + f_div
        scores.append({**c.to_dict(), "f_sweep": f_sweep, "f_choch": f_choch, "f_zone_stack": f_zone_stack,
                        "f_crt": f_crt, "f_bias": f_bias, "f_div": f_div, "score": score})
    return pd.DataFrame(scores)


def compute_stop_and_targets(qualified: pd.DataFrame, m15: pd.DataFrame, h1_zones: pd.DataFrame,
                              atr_by_bar: dict, crt_eq: pd.DataFrame,
                              target_max_atr_multiple: float = TARGET_MAX_ATR_MULTIPLE,
                              min_tp1_rr: float = MIN_TP1_RR) -> list:
    """Returns a list of qualifying signal dicts (TP1 R:R >= min_tp1_rr) --
    non-qualifying candidates are dropped entirely, not weakened, matching
    structural_tp_engine.py's own hard-floor convention. crt_eq: timeframe,
    bar_datetime, equilibrium_price (curated.crt_signals, signal_type='equilibrium').
    """
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
            "touch_time": t, "direction": direction, "score": int(c["score"]),
            "factors": {k: int(c[k]) for k in FACTOR_COLUMNS},
            "entry": entry, "stop": stop, "risk": risk,
            "targets": [(round(p, 5), src, round(dist / risk, 3)) for dist, p, src in levels[:5]],
            "tp1_price": tp1_price, "tp1_rr": tp1_rr,
            # Pass-through of the touched zone's own bounds -- additive,
            # backward compatible (existing consumers only read the keys
            # above). Lets callers match a result back to its source zone
            # (e.g. a Nested Zone Drilling chain) without re-deriving it.
            "zone_top": float(c["zone_top"]), "zone_bottom": float(c["zone_bottom"]),
        })

    # Results-level dedup: distinct overlapping zones touched at the exact
    # same bar can land on the identical final signal (entry/stop are fully
    # determined by touch_time/direction alone) -- one real signal, not N.
    seen = {}
    for r in results:
        key = (r["touch_time"], r["direction"])
        if key not in seen or r["score"] > seen[key]["score"]:
            seen[key] = r
    return list(seen.values())
