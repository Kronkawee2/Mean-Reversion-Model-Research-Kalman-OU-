"""
Structural TP Engine: computes a dynamic TP/R:R for a confirmed LTF trigger
by reading market structure, not by choosing a ratio.

This is "Option 2" from the design discussion (confirmed with the user over
two alternatives): direct confluence-score scaling was rejected for ignoring
whether price has room to actually travel before hitting a wall, and a
confluence-weighted hybrid was rejected for stacking two independent sets of
fittable constants on top of each other -- the wrong direction to go with
under 2 years of one-directional (gold bull run) history. This engine
avoids that trap: every constant it has (STRUCTURAL_TP_FRACTION,
MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE) is a structural-safety bound
on top of a real structural read, not a performance-fitted parameter --
none of them change WHAT the stop/target are derived from, only how far
that structural read is allowed to stretch before it's numerically
unreasonable.

Mechanics, per trigger:
  - entry_price: the LTF close at confirmed_at_bar (the actual actionable
    moment a live system would have this signal at).
  - stop_price: the FAR edge of the trigger's own htf_zone (htf_zone_bottom
    for a bullish trigger, htf_zone_top for a bearish one) -- if price
    breaks back through that edge, the zone that produced this signal is
    invalidated, so it's the natural stop-loss level. Capped at
    MAX_STOP_ATR_MULTIPLE * atr_14 (see below) -- the zone edge is still
    the reference, this only bounds how far away it's allowed to be.
  - opposing zone: the nearest active zone of the OPPOSITE direction ahead
    of price (e.g. for a bullish trigger, the nearest bearish
    order_block/fvg/swing_resistance zone whose near edge sits above
    entry_price). Its near edge (the boundary price reaches first) is the
    100% structural target.
  - target_price: entry + STRUCTURAL_TP_FRACTION * (opposing near edge -
    entry), not the full distance -- zones are ranges, not points, and
    price commonly reacts before fully tagging even the near edge.
  - structural_rr = (target_price - entry_price) / (entry_price -
    stop_price), i.e. computed directly from real structure, never chosen.

STRUCTURAL_TP_FRACTION = 0.85, proposed as a starting point, NOT a settled
constant -- same flag as CONFIRMATION_WINDOW_BARS in ltf_trigger_engine.py.
Reasoning for 0.85: using the opposing zone's NEAR edge (not its center or
far edge) as the 100% reference already bakes in one layer of conservatism
(we're not aiming past the first boundary price would reach). The
additional trim mainly guards against the common case where price reacts
and reverses slightly before fully tagging even that near edge. 0.85 is the
midpoint of the 80-90% range discussed with the user -- a defensible
starting point, not cherry-picked from either end, and explicitly subject
to revision once backtested.

Causality (no-lookahead): the opposing-zone search only considers zones
with created_at_bar <= confirmed_at_bar, and not yet invalidated as of
confirmed_at_bar (invalidated_at_bar is NULL or > confirmed_at_bar) -- the
exact same active-window pattern already used by htf_bias_engine.py and
ltf_trigger_engine.py's own touch detection. A trigger can never reference
a zone that didn't exist yet, or that had already been invalidated, at the
moment it fired.

Minimum stop-distance floor (target_status = 'stop_too_tight'): when
confirmed_at_bar's LTF close happens to land very close to the trigger
zone's own far edge (the stop), risk approaches zero and structural_rr
blows up independent of actual reward -- found via real data: 3 of the
top-3 R:R outliers (92.7, 80.9, 65.4) all had risk distances under 0.35
price points, orders of magnitude tighter than the zone geometry that
produced them. This is a numerical-stability fix, not a performance-tuning
knob -- a division-near-zero artifact is mathematically meaningless
regardless of what the backtester would say about it, so it's excluded
here rather than left for the backtester to (incorrectly) score.

MIN_RISK_ATR_MULTIPLE = 0.5, i.e. risk must be at least half of the h1
ATR-14 at the h1 bar containing confirmed_at_bar, else the trigger is
flagged 'stop_too_tight' and skipped (NULL target/rr), same treatment as
'no_opposing_zone'. ATR-based rather than a fixed price floor because gold
itself ranged from ~$2,500 to ~$5,500 across this dataset -- a fixed
dollar floor would be comparatively tiny at the high end and comparatively
large at the low end, whereas ATR adapts to the volatility regime at the
time each signal fired. 0.5x is a starting point, same "unvalidated, flag
it" discipline as STRUCTURAL_TP_FRACTION and CONFIRMATION_WINDOW_BARS --
not a settled constant. Requires atr_14 (h1) joined onto each trigger by
the caller; a trigger with no matching ATR value is also flagged
'stop_too_tight' rather than silently let through unguarded.

Maximum stop-distance cap (MAX_STOP_ATR_MULTIPLE = 1.5): the TP/SL problem
this was added to fix -- median structural_rr sat at 0.21 (real data,
XAUUSD choch_only), i.e. the typical stop was roughly 4-5x wider than the
typical target. Measured risk and reward separately in ATR terms to find
out which side was responsible before touching either: risk averaged
1.92x ATR-14 (median 1.69x) while reward averaged only 0.55x ATR-14
(median 0.36x) -- the stop side, not target selection, is what's out of
proportion. STRUCTURAL_TP_FRACTION and the nearest-opposing-zone target
logic were left alone because there was no comparable evidence of a
problem there.

Considered three fixes: (a) stop at the nearest LTF swing that formed the
CHoCH instead of the HTF zone's far edge -- the most "textbook SMC"
answer, but SMCStructureEngine.detect_bos_choch() doesn't currently
persist the swing price alongside each trigger, so this would mean
re-deriving LTF swing structure per trigger and introduces its own
unvalidated assumption (which pivot, wick vs. close) for an untested
payoff; (b) replace the zone-based stop with a pure ATR multiple (already
available as stop_mode='atr' for the variant-comparison script) -- tested
at 1.0/1.5/2.0/2.5x ATR on real data, 1.0x gave the single best median
improvement (0.21 -> 0.37) but abandons "the zone that produced the
signal is what invalidates it" entirely, the same reasoning Option 1
(direct confluence scaling) was rejected for -- structure stops being
influenced by structure was the whole premise of choosing this engine
over the alternatives; (c) keep the zone-far-edge stop as the reference
but cap it at a multiple of ATR-14, so a signal from an unusually wide
zone can't blow the stop out past what's volatility-reasonable, while a
signal from a normal-width zone is completely unaffected. Chose (c): it's
a numerical-safety bound on an existing structural read, not a new
performance-tuned parameter, the same class of fix MIN_RISK_ATR_MULTIPLE
already established for the floor side. Tested cap multiples 1.5/2.0/2.5/
3.0x on real data; 1.5x gave the best real improvement of the capped
variants (median structural_rr 0.21 -> 0.28, +33%) while remaining the
most conservative (tightest) cap tested, so it's the one used -- same
"defensible starting point, not cherry-picked from an extreme, explicitly
revisable" status as STRUCTURAL_TP_FRACTION's 0.85. Requires atr_14 same
as the floor; a trigger missing it is unaffected by the cap (the floor
check already flags it 'stop_too_tight' first).

Fallback when no eligible opposing zone exists (target_status =
'no_opposing_zone'): SKIP, not a default R:R. A default ratio here would
silently reintroduce exactly the flaw Option 1 was rejected for (an
arbitrary number disconnected from structure) -- and precisely for the
trades with the LEAST structural information, which in a one-directional
bull-run dataset could be a large, systematically-biased slice (e.g. every
signal fired during an uninterrupted trend with no resistance printed yet).
Mixing a structural R:R and a fallback R:R in the same output would also
make any later backtest ambiguous -- you couldn't tell whether performance
differences came from genuine structural sizing or fallback contamination.
Skipped triggers still get a row (target_status set, target/rr NULL) rather
than vanishing silently, so the skip rate itself is visible and reportable.

target_status = 'invalid_geometry' covers the (expected to be rare) edge
case where entry_price has already breached stop_price by the time this
runs -- risk <= 0, so no R:R can be computed.

No max-distance cap is imposed on how far an opposing zone can be. That
would be a second tunable constant, working against the "fewest tunable
parameters" reasoning behind choosing this approach at all -- outlier R:R
values are left visible in the output distribution for the user to judge,
rather than silently clipped.

This module deliberately produces a MECHANISM, not a validated performance
claim: the resulting R:R distribution shows whether structural TP behaves
sensibly (no lookahead, no absurd outliers, sane spread), not whether it
produces good trading outcomes. That question belongs to the backtester.
"""

import numpy as np
import pandas as pd

from analysis.strategies.ltf_trigger_engine import BULLISH_ZONE_TYPES, BEARISH_ZONE_TYPES

STRUCTURAL_TP_FRACTION = 0.85
MIN_RISK_ATR_MULTIPLE = 0.5
MAX_STOP_ATR_MULTIPLE = 1.5

STRUCTURAL_TP_COLUMNS = [
    "entry_price", "stop_price",
    "opposing_zone_type", "opposing_zone_top", "opposing_zone_bottom",
    "target_price", "structural_rr", "target_status",
]


def compute_structural_targets(
    triggers: pd.DataFrame,
    htf_zones: pd.DataFrame,
    fraction: float = STRUCTURAL_TP_FRACTION,
    min_risk_atr_multiple: float = MIN_RISK_ATR_MULTIPLE,
    max_stop_atr_multiple: float = MAX_STOP_ATR_MULTIPLE,
    stop_mode: str = "zone_far_edge",
    atr_stop_multiple: float = 1.5,
) -> pd.DataFrame:
    """
    triggers: one row per confirmed LTF trigger, must have columns
        direction, htf_zone_top, htf_zone_bottom, confirmed_at_bar,
        entry_price (LTF close at confirmed_at_bar, joined in by the caller),
        atr_14 (h1 ATR-14 at the h1 bar containing confirmed_at_bar, joined
        in by the caller -- used for the min/max stop-distance bounds, and
        for the stop itself when stop_mode='atr').
    htf_zones: zone_type, zone_top, zone_bottom, created_at_bar,
               invalidated_at_bar (curated.smc_signals, timeframe='h1').
    stop_mode: 'zone_far_edge' (default, the production behavior -- stop is
        the far edge of the trigger's own htf_zone, capped at
        max_stop_atr_multiple * atr_14 so an unusually wide zone can't
        blow the stop out past what's volatility-reasonable -- see the
        module docstring's "Maximum stop-distance cap" section) or 'atr'
        (stop is entry -/+ atr_stop_multiple * atr_14 with no zone
        reference at all, exploratory -- used only for the stop/target
        risk-mechanics comparison run alongside the production backtest,
        not itself a persisted default; see
        scripts/backtest/compare_structural_tp_variants.py).
    Returns triggers with STRUCTURAL_TP_COLUMNS appended (same row order,
    same index).
    """
    if stop_mode not in ("zone_far_edge", "atr"):
        raise ValueError(f"stop_mode must be 'zone_far_edge' or 'atr', got {stop_mode!r}")

    out = triggers.reset_index(drop=True).copy()
    for col in STRUCTURAL_TP_COLUMNS:
        if col != "entry_price":
            out[col] = None

    zones = htf_zones.reset_index(drop=True).copy()
    zone_created = pd.to_datetime(zones["created_at_bar"]).values.astype("datetime64[ns]")
    zone_invalidated_raw = pd.to_datetime(zones["invalidated_at_bar"])
    zone_invalidated_isnull = zone_invalidated_raw.isna().values
    zone_invalidated = zone_invalidated_raw.values.astype("datetime64[ns]")
    zone_type = zones["zone_type"].values
    zone_top = zones["zone_top"].astype(float).values
    zone_bottom = zones["zone_bottom"].astype(float).values

    for idx, row in out.iterrows():
        direction = row["direction"]
        entry = float(row["entry_price"])
        confirmed_at = np.datetime64(pd.Timestamp(row["confirmed_at_bar"]))

        atr = row.get("atr_14")

        if stop_mode == "atr":
            if pd.isnull(atr):
                out.at[idx, "entry_price"] = entry
                out.at[idx, "target_status"] = "stop_too_tight"
                continue
            stop = entry - atr_stop_multiple * float(atr) if direction == "bullish" \
                else entry + atr_stop_multiple * float(atr)
        else:
            stop = float(row["htf_zone_bottom"]) if direction == "bullish" else float(row["htf_zone_top"])
            if pd.notnull(atr):
                zone_risk = (entry - stop) if direction == "bullish" else (stop - entry)
                max_risk = max_stop_atr_multiple * float(atr)
                if zone_risk > max_risk:
                    stop = entry - max_risk if direction == "bullish" else entry + max_risk

        risk = (entry - stop) if direction == "bullish" else (stop - entry)
        out.at[idx, "entry_price"] = entry
        out.at[idx, "stop_price"] = stop

        if risk <= 0:
            out.at[idx, "target_status"] = "invalid_geometry"
            continue

        min_risk = min_risk_atr_multiple * float(atr) if pd.notnull(atr) else None
        if min_risk is None or risk < min_risk:
            out.at[idx, "target_status"] = "stop_too_tight"
            continue

        opposing_types = BEARISH_ZONE_TYPES if direction == "bullish" else BULLISH_ZONE_TYPES
        type_mask = np.isin(zone_type, list(opposing_types))
        causal_mask = (zone_created <= confirmed_at) & (zone_invalidated_isnull | (zone_invalidated > confirmed_at))
        candidate_mask = type_mask & causal_mask

        if direction == "bullish":
            near_edge = zone_bottom
            side_mask = candidate_mask & (near_edge > entry)
        else:
            near_edge = zone_top
            side_mask = candidate_mask & (near_edge < entry)

        candidates = np.where(side_mask)[0]

        if len(candidates) == 0:
            out.at[idx, "target_status"] = "no_opposing_zone"
            continue

        if direction == "bullish":
            best = candidates[np.argmin(near_edge[candidates])]  # nearest above entry
        else:
            best = candidates[np.argmax(near_edge[candidates])]  # nearest below entry

        edge = float(near_edge[best])
        reward_full = (edge - entry) if direction == "bullish" else (entry - edge)
        reward = fraction * reward_full
        target = entry + reward if direction == "bullish" else entry - reward
        rr = reward / risk

        out.at[idx, "opposing_zone_type"] = zone_type[best]
        out.at[idx, "opposing_zone_top"] = float(zone_top[best])
        out.at[idx, "opposing_zone_bottom"] = float(zone_bottom[best])
        out.at[idx, "target_price"] = target
        out.at[idx, "structural_rr"] = rr
        out.at[idx, "target_status"] = "structural"

    return out
