"""
Confluence LTF Trigger: wraps LTFTriggerEngine UNCHANGED, sourcing HTF
zones from confluence_zones (multi-factor, h4) instead of smc_signals'
single-factor h1 zones. See docs/DECISIONS.md for the full design
(approved after a real-data walkthrough of 3 concrete confluence zones).

LTFTriggerEngine.compute_triggers() itself is not modified -- it just
needs a zone_type it understands to look up bullish/bearish
(BULLISH_ZONE_TYPES/BEARISH_ZONE_TYPES). Confluence zones already carry
`direction` directly, so a same-direction proxy type ('swing_support'/
'swing_resistance', arbitrary picks from the existing set purely to
satisfy that lookup) is used internally for the call and then replaced
on the way out with 'confluence_bullish_mode_a'/'confluence_bullish_mode_b'/
'confluence_bearish_mode_a'/'confluence_bearish_mode_b' -- the real
type persisted to ltf_trigger_signals.

Touch detection always runs against the zone's FULL range (matches
single-factor-zone recall -- doesn't cost any signals). Core-first-
fallback-to-full range selection: once a trigger confirms, if the LTF
entry price (close at confirmed_at_bar) also falls inside the zone's
CORE range (the intersection of its ranged factors -- the double/triple-
confirmed overlap), the trigger's htf_zone_top/htf_zone_bottom are
swapped to CORE for everything downstream (stop distance via
structural_tp_engine.py, itself unmodified -- it just reads whatever
zone boundary it's given). Otherwise FULL stays, identical to a
single-factor zone's behavior today. zone_range_used records which one
was used, so full-vs-core performance can be compared later without
re-deriving it.

Real-data walkthrough before building found both real benefits and real
costs to this rule, not smoothed over: requiring CORE can cost several
days of confirmation delay relative to FULL (one real zone: 4 days), and
structural_tp_engine.py's ATR stop cap often makes FULL and CORE produce
an IDENTICAL final stop anyway (the cap, not the raw zone edge, ends up
binding) -- CORE's tightening only shows up when its raw distance is
already inside the ATR cap. Both are real, observed trade-offs, not
optimized away.

Scope this pass: h4 confluence zones only (h6/d1 not wired in here --
same "pick one primary HTF, extend later" precedent as h1 for the
original single-factor triggers). ltf_timeframe='m15' only (m5 supported
by the underlying engine but not run this pass, to keep the 4-variant
comparison scope explicit per the user's approval).
"""

import numpy as np
import pandas as pd

from analysis.strategies.ltf_trigger_engine import LTFTriggerEngine, LTF_TRIGGER_COLUMNS

CONFLUENCE_ZONE_TYPE_PROXY = {"bullish": "swing_support", "bearish": "swing_resistance"}

# Encodes BOTH direction and confluence mode -- not just direction. This
# matters for correctness, not just labeling: ltf_trigger_signals' legacy
# uq_trigger unique key (symbol, ltf_timeframe, mode, htf_zone_type,
# htf_zone_created_at_bar, touch_bar_datetime, choch_bar_datetime) has no
# way to know about confluence_mode, and a mode_b_3factor zone is BY
# DEFINITION also a mode_a_2factor zone of the same underlying cluster --
# same last_factor_at_bar, so an early version of this module that used a
# single direction-only proxy here produced identical uq_trigger keys for
# both modes' triggers, and MySQL's ON DUPLICATE KEY UPDATE silently
# merged mode_b's rows into mode_a's, losing them (see docs/DECISIONS.md).
# Baking the mode into htf_zone_type itself is what makes the existing key
# distinguish them without changing the key's column list.
CONFLUENCE_PERSISTED_TYPE = {
    ("bullish", "mode_a_2factor"): "confluence_bullish_mode_a",
    ("bullish", "mode_b_3factor"): "confluence_bullish_mode_b",
    ("bearish", "mode_a_2factor"): "confluence_bearish_mode_a",
    ("bearish", "mode_b_3factor"): "confluence_bearish_mode_b",
}

CONFLUENCE_TRIGGER_COLUMNS = LTF_TRIGGER_COLUMNS + [
    "entry_price", "zone_source", "confluence_zone_id", "confluence_mode", "zone_range_used",
]


def build_confluence_zone_frame(zones: pd.DataFrame) -> pd.DataFrame:
    """zones: confluence_zones rows (id, direction, zone_full_top/bottom,
    zone_core_top/bottom, last_factor_at_bar, status, resolved_at_bar).
    Returns the shape LTFTriggerEngine.compute_triggers() AND
    structural_tp_engine.compute_structural_targets() both expect (zone_type,
    zone_top, zone_bottom, created_at_bar, invalidated_at_bar) -- reused for
    BOTH the entry-side touch/CHoCH zone set (see compute_confluence_triggers
    below) and the opposing-zone target search (see
    scripts/detection/run_confluence_ltf_triggers.py's confluence-aware
    target-selection pass, docs/DECISIONS.md) -- same proxy zone_type
    ('swing_support'/'swing_resistance') either way, since both callers only
    need it to resolve to the right bullish/bearish bucket, not to claim a
    specific single-factor pattern.

    Always FULL range, not core -- entry-side touch detection needs full
    range for recall (core swap-in happens after confirmation, in
    compute_confluence_triggers); the opposing-zone target search uses full
    range as the natural "first point price reaches this structure" edge,
    consistent with full_range's own definition as the union of every
    contributing factor.

    created_at_bar = last_factor_at_bar, not the cluster's first factor's
    timestamp -- the confluence zone doesn't exist as an N-factor zone
    until its LAST contributing factor forms; using the first factor's
    timestamp would let LTF triggers confirm against a zone that, at that
    moment, didn't actually have all its factors yet (lookahead)."""
    return pd.DataFrame({
        "zone_type": zones["direction"].map(CONFLUENCE_ZONE_TYPE_PROXY),
        "zone_top": zones["zone_full_top"].astype(float),
        "zone_bottom": zones["zone_full_bottom"].astype(float),
        "created_at_bar": pd.to_datetime(zones["last_factor_at_bar"]),
        "invalidated_at_bar": pd.to_datetime(zones["resolved_at_bar"]).where(zones["status"] == "invalidated"),
    })


def compute_confluence_triggers(
    ltf_bars: pd.DataFrame,
    confluence_zones: pd.DataFrame,
    symbol: str,
    ltf_timeframe: str = "m15",
    mode: str = "choch_only",
) -> pd.DataFrame:
    """
    ltf_bars: price_datetime, high_price, low_price, close_price (raw
        m5/m15), sorted ascending.
    confluence_zones: one confluence MODE's worth of rows (id, direction,
        zone_full_top/bottom, zone_core_top/bottom, last_factor_at_bar,
        status, resolved_at_bar) -- caller filters to a single
        mode_a_2factor/mode_b_3factor before calling, same as how the
        original engine is called once per htf-zone-set.
    mode: LTF confirmation mode ('choch_only'/'choch_sweep'), passed
        straight through to LTFTriggerEngine -- unrelated to the
        confluence zone's own mode above; they vary independently (2x2).
    Returns one row per confirmed trigger, CONFLUENCE_TRIGGER_COLUMNS.
    """
    if confluence_zones.empty or ltf_bars.empty:
        return pd.DataFrame(columns=CONFLUENCE_TRIGGER_COLUMNS)

    base = ltf_bars.reset_index(drop=True).copy()
    base["price_datetime"] = pd.to_datetime(base["price_datetime"])

    zones = confluence_zones.reset_index(drop=True).copy()
    htf_zones = build_confluence_zone_frame(zones)

    trig = LTFTriggerEngine().compute_triggers(
        base, htf_zones, symbol=symbol, ltf_timeframe=ltf_timeframe, mode=mode,
    )
    if trig.empty:
        return pd.DataFrame(columns=CONFLUENCE_TRIGGER_COLUMNS)

    # Join each trigger back to the confluence zone it came from. Full
    # range's top/bottom + created_at_bar (= last_factor_at_bar) + direction
    # is what compute_triggers() copied straight through from htf_zones, so
    # it's a safe key against the same single-mode zone set this call used.
    zones_keyed = zones.rename(columns={
        "last_factor_at_bar": "htf_zone_created_at_bar",
        "zone_full_top": "htf_zone_top", "zone_full_bottom": "htf_zone_bottom",
    })
    zones_keyed["htf_zone_created_at_bar"] = pd.to_datetime(zones_keyed["htf_zone_created_at_bar"])
    zones_keyed["htf_zone_top"] = zones_keyed["htf_zone_top"].astype(float)
    zones_keyed["htf_zone_bottom"] = zones_keyed["htf_zone_bottom"].astype(float)

    out = trig.merge(
        zones_keyed[["id", "mode", "direction", "htf_zone_created_at_bar", "htf_zone_top", "htf_zone_bottom",
                     "zone_core_top", "zone_core_bottom"]],
        on=["direction", "htf_zone_created_at_bar", "htf_zone_top", "htf_zone_bottom"],
        how="left", suffixes=("", "_zone"),
    )
    out = out.rename(columns={"id": "confluence_zone_id", "mode_zone": "confluence_mode"})

    entry_by_bar = base.set_index("price_datetime")["close_price"].astype(float)
    out["entry_price"] = out["confirmed_at_bar"].map(entry_by_bar)

    within_core = (
        (out["entry_price"] >= out["zone_core_bottom"].astype(float))
        & (out["entry_price"] <= out["zone_core_top"].astype(float))
    )
    out["zone_range_used"] = np.where(within_core, "core", "full")
    out.loc[within_core, "htf_zone_top"] = out.loc[within_core, "zone_core_top"].astype(float)
    out.loc[within_core, "htf_zone_bottom"] = out.loc[within_core, "zone_core_bottom"].astype(float)

    out["htf_zone_type"] = [CONFLUENCE_PERSISTED_TYPE[(d, m)] for d, m in zip(out["direction"], out["confluence_mode"])]
    out["zone_source"] = "confluence_zone"

    return out[CONFLUENCE_TRIGGER_COLUMNS]
