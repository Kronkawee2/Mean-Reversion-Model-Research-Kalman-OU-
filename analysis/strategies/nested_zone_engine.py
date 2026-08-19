"""
Nested Zone Drilling -- the LTF zoom-in piece (see docs/DECISIONS.md).

Starts from any qualifying active/mitigated zone at D1, H6, H4, or H1 (no
requirement to start at D1) and drills down through the fixed hierarchy
D1 > H6 > H4 > H1 > M15 > M5, at each level keeping only same-direction
zones (OB/FVG/swing) whose price range is nested inside the current
parent's range AND whose created_at_bar is on/after the parent's
(temporal causality -- a child zone must have formed while the parent was
still live, not an unrelated coincidence of price overlap from a different
regime). Among valid candidates at a level, advances into the TIGHTEST one
(smallest zone_top - zone_bottom).

An intermediate HTF level (H6/H4/H1) with no valid nested zone is SKIPPED,
not fatal -- drilling continues from the same parent into the next finer
level. The LTF step (M15, falling back to M5) is NOT optional: a chain
that fails to find a valid nested zone at M15 or M5 is discarded entirely
(see build_nested_chains) -- the whole point is guaranteeing an
LTF-anchored entry, not silently falling back to an HTF zone's own
(much wider) range.

Zone detection at every level reuses SMCZoneStateEngine.detect_zones()
UNCHANGED -- confirmed timeframe-agnostic (it only needs an OHLC df and a
timeframe label), so M15/M5 zone detection is not a new engine, just a new
invocation of the same one already used for h1/h4/h6/d1.

The output of build_nested_chains() is a full chain per candidate PLUS a
terminal-zone row shaped exactly like an h1_zones row (zone_type,
zone_top, zone_bottom, created_at_bar, invalidated_at_bar) so it can be fed
directly into composite_confluence_engine.build_candidates() as a drop-in
replacement for h1 zones -- the touch-detection, scoring, stop/target, and
resolution logic downstream are 100% reused unchanged. This module only
ever replaces WHERE the candidate anchor zone comes from, never how a
touch becomes a scored/resolved signal.
"""

import pandas as pd

from analysis.smc_crt.zone_state import SMCZoneStateEngine
from analysis.strategies.ltf_trigger_engine import BULLISH_ZONE_TYPES, BEARISH_ZONE_TYPES
from analysis.strategies import composite_confluence_engine as cce

HIERARCHY = ["d1", "h6", "h4", "h1", "m15", "m5"]
HTF_LEVELS = ("d1", "h6", "h4", "h1")
LTF_WINDOW_DAYS = 5  # bounded window for on-demand M15/M5 detection per chain attempt
MIN_LTF_BARS = 10


def _zone_direction(zone_type):
    if zone_type in BULLISH_ZONE_TYPES:
        return "bullish"
    if zone_type in BEARISH_ZONE_TYPES:
        return "bearish"
    return None


def _zone_types_for(direction):
    return BULLISH_ZONE_TYPES if direction == "bullish" else BEARISH_ZONE_TYPES


def _zone_dict(row):
    return {
        "zone_type": row["zone_type"],
        "zone_top": float(row["zone_top"]),
        "zone_bottom": float(row["zone_bottom"]),
        "created_at_bar": str(pd.Timestamp(row["created_at_bar"])),
        "state": row.get("state", "active"),
    }


def _tightest_nested(zones_df, direction, parent_top, parent_bottom, parent_created):
    """Zones of zones_df strictly nested inside [parent_bottom, parent_top],
    formed on/after parent_created, same direction, still active/mitigated.
    Returns the tightest (smallest range) row, or None."""
    if zones_df is None or zones_df.empty:
        return None
    same = _zone_types_for(direction)
    cand = zones_df[
        zones_df["zone_type"].isin(same)
        & (pd.to_datetime(zones_df["created_at_bar"]) >= parent_created)
        & (zones_df["zone_bottom"].astype(float) >= parent_bottom)
        & (zones_df["zone_top"].astype(float) <= parent_top)
        & (zones_df["state"].isin(["active", "mitigated"]))
    ]
    if cand.empty:
        return None
    widths = cand["zone_top"].astype(float) - cand["zone_bottom"].astype(float)
    return cand.loc[widths.idxmin()]


def _drill_ltf(m15_raw, m5_raw, symbol, direction, parent_top, parent_bottom, parent_created):
    """Try M15 first (preferred terminal per the design); if a valid nested
    M15 zone is found, try one more level into M5 nested inside THAT M15
    zone for extra tightness (kept only if found, M15 stays terminal
    otherwise). If M15 finds nothing, fall back to M5 nested directly in
    the HTF parent. Returns (terminal_timeframe, row) or (None, None)."""
    window_end = parent_created + pd.Timedelta(days=LTF_WINDOW_DAYS)

    m15_window = m15_raw[(m15_raw["price_datetime"] >= parent_created) & (m15_raw["price_datetime"] <= window_end)]
    if len(m15_window) >= MIN_LTF_BARS:
        m15_zones = SMCZoneStateEngine().detect_zones(m15_window.reset_index(drop=True), symbol=symbol, timeframe="m15")
        m15_cand = _tightest_nested(m15_zones, direction, parent_top, parent_bottom, parent_created)
        if m15_cand is not None:
            m15_top, m15_bottom = float(m15_cand["zone_top"]), float(m15_cand["zone_bottom"])
            m15_created = pd.Timestamp(m15_cand["created_at_bar"])
            m5_window = m5_raw[(m5_raw["price_datetime"] >= m15_created) & (m5_raw["price_datetime"] <= window_end)]
            if len(m5_window) >= MIN_LTF_BARS:
                m5_zones = SMCZoneStateEngine().detect_zones(m5_window.reset_index(drop=True), symbol=symbol, timeframe="m5")
                m5_cand = _tightest_nested(m5_zones, direction, m15_top, m15_bottom, m15_created)
                if m5_cand is not None:
                    return "m5", m5_cand
            return "m15", m15_cand

    m5_window = m5_raw[(m5_raw["price_datetime"] >= parent_created) & (m5_raw["price_datetime"] <= window_end)]
    if len(m5_window) >= MIN_LTF_BARS:
        m5_zones = SMCZoneStateEngine().detect_zones(m5_window.reset_index(drop=True), symbol=symbol, timeframe="m5")
        m5_cand = _tightest_nested(m5_zones, direction, parent_top, parent_bottom, parent_created)
        if m5_cand is not None:
            return "m5", m5_cand

    return None, None


def _drill_from_root(root_tf, root_row, symbol, htf_zones_by_tf, m15_raw, m5_raw):
    direction = _zone_direction(root_row["zone_type"])
    if direction is None:
        return None

    chain = [{"timeframe": root_tf, **_zone_dict(root_row)}]
    parent_top = float(root_row["zone_top"])
    parent_bottom = float(root_row["zone_bottom"])
    parent_created = pd.Timestamp(root_row["created_at_bar"])

    start_idx = HIERARCHY.index(root_tf)
    for tf in HIERARCHY[start_idx + 1:]:
        if tf in ("m15", "m5"):
            break
        cand = _tightest_nested(htf_zones_by_tf.get(tf), direction, parent_top, parent_bottom, parent_created)
        if cand is not None:
            chain.append({"timeframe": tf, **_zone_dict(cand)})
            parent_top, parent_bottom = float(cand["zone_top"]), float(cand["zone_bottom"])
            parent_created = pd.Timestamp(cand["created_at_bar"])

    terminal_tf, terminal = _drill_ltf(m15_raw, m5_raw, symbol, direction, parent_top, parent_bottom, parent_created)
    if terminal is None:
        return None  # discard -- no valid LTF nest, per the confirmed design rule

    chain.append({"timeframe": terminal_tf, **_zone_dict(terminal)})

    return {
        "symbol": symbol,
        "direction": direction,
        "root_timeframe": root_tf,
        "terminal_timeframe": terminal_tf,
        "chain": chain,
        "zone_type": terminal["zone_type"],
        "zone_top": float(terminal["zone_top"]),
        "zone_bottom": float(terminal["zone_bottom"]),
        "created_at_bar": pd.Timestamp(terminal["created_at_bar"]),
        "invalidated_at_bar": pd.Timestamp(terminal["invalidated_at_bar"]) if pd.notnull(terminal.get("invalidated_at_bar")) else None,
    }


def filter_roots_near_composite_factors(zones_by_tf: dict, sweeps: pd.DataFrame, choch: pd.DataFrame,
                                         all_tf_zones: pd.DataFrame, htf_bias: pd.DataFrame,
                                         divs: pd.DataFrame) -> dict:
    """Pre-filter ROOT candidates only (not the intermediate-level search
    pool, see build_nested_chains' root_zones_by_tf param) to zones with AT
    LEAST 2 of the same 5 factors composite scoring already checks --
    sweep, CHoCH, zone_stack, bias, divergence, reusing that exact factor
    set rather than a subset -- present near the zone. Prioritizes
    composite-relevant zones BEFORE spending compute drilling them,
    instead of drilling every active/mitigated zone and discovering only
    after the fact (via the composite score, evaluated on the touch) that
    most drilled chains have no composite factor support nearby at all.

    First version of this filter (single-factor OR, days-wide window) was
    tested and found completely non-selective (100% of roots kept, see
    docs/DECISIONS.md) -- sweep/CHoCH/bias/divergence are each individually
    common enough over a multi-day window that ORing 5 of them together is
    nearly always true. Fixed two ways: (1) reused the EXACT windows
    score_candidates() itself uses to judge these factors at touch-time --
    TOUCH_WINDOW_M15_BARS (5h) for sweep/CHoCH, DIVERGENCE_LOOKBACK_H1_BARS
    (20h) for divergence, "latest reading at/before this moment" (a
    snapshot, not a window) for bias -- instead of an arbitrary multi-day
    window; (2) require 2+ factors present, not just 1 of 5.

    sweeps: direction, swept_level_price, bar_datetime. choch: direction
    encoded in smc_structure_signal, close_price, price_datetime. Both
    checked as price-anchored events within TOUCH_WINDOW_M15_BARS-worth of
    time after the zone's formation (price inside the zone's own range,
    same direction).

    all_tf_zones: zone_type, zone_top, zone_bottom, created_at_bar,
    invalidated_at_bar, timeframe, state -- checked as "does at least one
    OTHER zone (any of h1/h4/h6/d1) overlap this root's range with combined
    ZONE_TIMEFRAME_WEIGHT >= 2" AT THE MOMENT the root zone formed (a
    snapshot, same as f_zone_stack's own touch-time evaluation), applied to
    the root zone itself.

    htf_bias: bar_datetime, bias. divs: bar_datetime, direction. Bias is a
    snapshot (latest reading at/before the zone's formation, matching how
    f_bias itself is evaluated -- never a window). Divergence uses
    DIVERGENCE_LOOKBACK_H1_BARS after formation, matching f_div's own
    lookback."""
    sweep_choch_window = pd.Timedelta(minutes=15 * cce.TOUCH_WINDOW_M15_BARS)
    div_window = pd.Timedelta(hours=cce.DIVERGENCE_LOOKBACK_H1_BARS)
    filtered = {}
    for tf, zones in zones_by_tf.items():
        if zones is None or zones.empty:
            filtered[tf] = zones
            continue
        keep = []
        for _, z in zones.iterrows():
            direction = _zone_direction(z["zone_type"])
            if direction is None:
                keep.append(False)
                continue
            created = pd.Timestamp(z["created_at_bar"])
            top, bottom = float(z["zone_top"]), float(z["zone_bottom"])

            near_sweep = False
            if sweeps is not None and not sweeps.empty:
                cand = sweeps[
                    (sweeps["direction"] == direction)
                    & (pd.to_datetime(sweeps["bar_datetime"]) >= created)
                    & (pd.to_datetime(sweeps["bar_datetime"]) <= created + sweep_choch_window)
                    & (sweeps["swept_level_price"].astype(float) >= bottom)
                    & (sweeps["swept_level_price"].astype(float) <= top)
                ]
                near_sweep = not cand.empty

            near_choch = False
            if choch is not None and not choch.empty:
                choch_dir = "BULLISH_CHOCH" if direction == "bullish" else "BEARISH_CHOCH"
                cand = choch[
                    (choch["smc_structure_signal"] == choch_dir)
                    & (pd.to_datetime(choch["price_datetime"]) >= created)
                    & (pd.to_datetime(choch["price_datetime"]) <= created + sweep_choch_window)
                    & (choch["close_price"].astype(float) >= bottom)
                    & (choch["close_price"].astype(float) <= top)
                ]
                near_choch = not cand.empty

            near_zone_stack = False
            if all_tf_zones is not None and not all_tf_zones.empty:
                same = _zone_types_for(direction)
                overlapping = all_tf_zones[
                    (all_tf_zones["zone_type"].isin(same))
                    & (all_tf_zones["created_at_bar"] <= created)
                    & (all_tf_zones["invalidated_at_bar"].isna() | (all_tf_zones["invalidated_at_bar"] > created))
                    & (all_tf_zones["zone_bottom"].astype(float) <= top)
                    & (all_tf_zones["zone_top"].astype(float) >= bottom)
                    & ~((all_tf_zones["zone_top"].astype(float) == top) & (all_tf_zones["zone_bottom"].astype(float) == bottom)
                        & (all_tf_zones["timeframe"] == tf))  # exclude the root zone itself
                ]
                weighted = overlapping["timeframe"].map(cce.ZONE_TIMEFRAME_WEIGHT).fillna(1).sum()
                near_zone_stack = weighted >= 2

            near_bias = False
            if htf_bias is not None and not htf_bias.empty:
                hb = htf_bias[pd.to_datetime(htf_bias["bar_datetime"]) <= created]
                if not hb.empty:
                    near_bias = hb.sort_values("bar_datetime").iloc[-1]["bias"] == direction

            near_div = False
            if divs is not None and not divs.empty:
                near_div = (
                    (divs["direction"] == direction)
                    & (pd.to_datetime(divs["bar_datetime"]) >= created)
                    & (pd.to_datetime(divs["bar_datetime"]) <= created + div_window)
                ).any()

            factor_count = sum([near_sweep, near_choch, near_zone_stack, near_bias, near_div])
            keep.append(factor_count >= 2)
        filtered[tf] = zones[pd.Series(keep, index=zones.index)]
    return filtered


def build_nested_chains(symbol: str, htf_zones_by_tf: dict, m15_raw: pd.DataFrame, m5_raw: pd.DataFrame,
                         root_zones_by_tf: dict = None) -> list:
    """htf_zones_by_tf: {'d1':df, 'h6':df, 'h4':df, 'h1':df}, each with
    columns zone_type, zone_top, zone_bottom, created_at_bar, state
    (curated.smc_signals rows for that timeframe). m15_raw/m5_raw: raw OHLC
    (price_datetime, high_price, low_price, close_price), sorted ascending.
    root_zones_by_tf: optional, same shape as htf_zones_by_tf -- if given,
    used ONLY to select which zones become chain ROOTS (e.g. the output of
    filter_roots_near_sweep_or_choch), while htf_zones_by_tf remains the
    FULL pool for intermediate-level nested-zone search once a chain has
    started -- prioritizing which zones are worth drilling should not also
    shrink what a chain can nest through once it's underway. Defaults to
    htf_zones_by_tf (every active/mitigated zone is a root candidate,
    original behavior) when not given.

    Returns one dict per valid (LTF-terminated) chain, shaped so the
    terminal zone alone (zone_type/zone_top/zone_bottom/created_at_bar/
    invalidated_at_bar) is a drop-in replacement for an h1_zones row.
    Deduplicated by terminal zone identity -- if multiple root zones drill
    down to literally the same terminal M15/M5 zone, only the richest
    (longest) chain reaching it is kept, since the resulting entry/stop
    would be identical either way."""
    root_zones_by_tf = root_zones_by_tf if root_zones_by_tf is not None else htf_zones_by_tf
    seen_terminal = {}
    for root_tf in HTF_LEVELS:
        roots = root_zones_by_tf.get(root_tf)
        if roots is None or roots.empty:
            continue
        for _, root_row in roots.iterrows():
            if root_row.get("state") not in ("active", "mitigated"):
                continue
            result = _drill_from_root(root_tf, root_row, symbol, htf_zones_by_tf, m15_raw, m5_raw)
            if result is None:
                continue
            key = (result["terminal_timeframe"], result["zone_type"],
                   result["zone_top"], result["zone_bottom"], result["created_at_bar"])
            if key not in seen_terminal or len(result["chain"]) > len(seen_terminal[key]["chain"]):
                seen_terminal[key] = result
    return list(seen_terminal.values())


def build_candidates_from_chains(m15: pd.DataFrame, chains: list) -> pd.DataFrame:
    """The alternate build_candidates() path: reshapes chain terminal zones
    into an h1_zones-shaped DataFrame and hands it straight to
    composite_confluence_engine.build_candidates() UNCHANGED -- touch
    detection, scoring, stop/target search, and resolution are all the
    exact same code the H1-touch mechanism uses. Only the candidate
    anchor's SOURCE changes (nested LTF-terminated chain vs. a bare h1
    zone); everything downstream is identical by construction, which is
    what makes the side-by-side comparison apples-to-apples."""
    if not chains:
        return cce.build_candidates(m15, pd.DataFrame(
            columns=["zone_type", "zone_top", "zone_bottom", "created_at_bar", "invalidated_at_bar", "timeframe"]))
    terminal_zones = pd.DataFrame([{
        "zone_type": c["zone_type"], "zone_top": c["zone_top"], "zone_bottom": c["zone_bottom"],
        "created_at_bar": c["created_at_bar"], "invalidated_at_bar": c["invalidated_at_bar"],
        "timeframe": c["terminal_timeframe"],  # m15 or m5 -- selects the LTF-appropriate formation gate
    } for c in chains])
    return cce.build_candidates(m15, terminal_zones)
