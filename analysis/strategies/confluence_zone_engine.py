"""
Confluence Zone Engine: combines HTF (h4/h6/d1) FVG, Order Block, swing
support/resistance, SMC CHoCH, and liquidity sweep (BSL/SSL) factors into
a single multi-factor confluence zone, rather than relying on one signal
type alone. Reuses SMCZoneStateEngine (FVG/OB/swing), SMCStructureEngine
(CHoCH), and LiquiditySweepStateEngine (sweep) unchanged -- this module
only adds the clustering/scoring layer on top, same additive-module
pattern as zone_state.py/crt_state.py/liquidity_state.py before it.

"CRT sweep" in the original design brief is mapped to LiquiditySweepStateEngine's
BSL/SSL sweep detection (not CRTStateEngine's Asian-session sweep, which is
an h1-specific session concept that doesn't generalize to h4/h6/d1) --
flagged explicitly since the brief didn't disambiguate this and it's a
real design choice, not an obvious one.

Two modes (confirmed with the user, both built as separate selectable
modes rather than picking one, same pattern as LTFTriggerEngine's
choch_only/choch_sweep):
  - mode_a_2factor: any 2 of the 5 factor types, equal weight.
  - mode_b_3factor: any 3 of the 5 factor types, equal weight.
CHoCH is NOT mandatory in either mode (confirmed with the user) -- a
zone built from FVG+OB alone, for example, is treated as a legitimate
2-factor confluence zone, same standing as one built from CHoCH+Sweep.

Clustering: factors of the SAME direction whose price ranges overlap (a
point-event factor -- CHoCH/Sweep -- is treated as a zero-width point at
its own price) AND whose timestamps fall within CONFLUENCE_TIME_WINDOW_BARS
of the cluster's most recently added factor get merged into one cluster.
Bar-count based (not a fixed hour window) so the same rule generalizes
across h4/h6/d1 without retuning -- 5 bars is ~20h at h4, ~30h at h6, ~5
days at d1, which was validated against real XAUUSD data during the
design-options survey (see docs/DECISIONS.md) as producing structurally
sensible clusters, not arbitrary chosen for this module specifically.

A second, independent bound -- CONFLUENCE_MAX_SPAN_BARS -- caps how far a
cluster's LAST factor can sit from its FIRST, since the gap-based rule
above resets its clock on every new member and would otherwise let a
chain of factors arriving just under the gap limit apart drift a cluster
arbitrarily far (a real XAUUSD h4 cluster spanned 4 calendar days via 14
factors each individually within the gap window of the previous one --
see docs/DECISIONS.md). A factor joins an existing cluster only if it
satisfies BOTH bounds; failing either one starts a new cluster instead.

Zone boundaries (confirmed with the user): zone_full_range is the UNION of
every contributing factor's price range (a point-event factor contributes
just its own price to the union's extent). zone_core_range is the
INTERSECTION of the contributing RANGED factors only (FVG/OB/SwingSR) --
CHoCH/Sweep are point events and can't meaningfully narrow an intersection,
so they're excluded from the core-range computation, only from the full
range. If fewer than 2 ranged factors contributed (e.g. a CHoCH+Sweep-only
cluster, possible if a stray FVG/OB/SwingSR happens not to overlap it),
zone_core_range falls back to equal zone_full_range -- there's no
meaningful narrower intersection to compute with 0-1 ranges.

Confidence score: factor_count itself (2-5), reported as "X/5" -- the
simplest explainable scheme, deliberately not a weighted/black-box formula
per the user's explicit instruction to keep this interpretable. A zone
with 4 stacking factors reads as literally "4 of the 5 possible factor
types agree here," nothing more, nothing hidden.

Status lifecycle: 'active' (default) or 'invalidated' (price closed
through zone_full_range on the wrong side after formation -- mirrors the
same close-through invalidation rule zone_state.py already uses for
individual OB/FVG zones, applied to the confluence zone's own full range).
'won'/'lost' are valid schema states but NOT set by this module -- those
depend on the LTF entry/exit outcome, which is explicitly a follow-up pass
not built here. A zone sits in 'active' until either invalidated by price
action or (in the follow-up pass) resolved by an LTF trade outcome.
"""

import pandas as pd

from analysis.smc_crt.zone_state import SMCZoneStateEngine
from analysis.smc_crt.structure import SMCStructureEngine
from analysis.smc_crt.liquidity_state import LiquiditySweepStateEngine

CONFLUENCE_TIME_WINDOW_BARS = 5

# Caps how far a cluster can drift from its OWN FIRST factor, independent of
# the rolling CONFLUENCE_TIME_WINDOW_BARS gap check above. Without this, a
# chain of factors arriving every <=5 bars apart can extend a single
# cluster indefinitely -- a real XAUUSD h4 example spanned 4 calendar days
# (24 bars) via 14 factors each individually within the 5-bar gap of the
# previous one, which reads more like "price kept respecting the same
# pivot for four days" than one coherent zone. Chose 15 bars (60h at h4,
# ~3x CONFLUENCE_TIME_WINDOW_BARS) after comparing 10/15/20-bar candidates
# against the real 726-day XAUUSD dataset (see docs/DECISIONS.md) --
# flagged, same as STRUCTURAL_TP_FRACTION/CONFIRMATION_WINDOW_BARS/
# SMC_ZONE_RECENCY_WINDOW_BARS, as a starting point validated against one
# symbol's real data, not swept/optimized.
CONFLUENCE_MAX_SPAN_BARS = 15

MODE_MIN_FACTORS = {"mode_a_2factor": 2, "mode_b_3factor": 3}

RANGED_ZONE_TYPES = {
    "order_block_bullish": ("bullish", "OB"), "order_block_bearish": ("bearish", "OB"),
    "fvg_bullish": ("bullish", "FVG"), "fvg_bearish": ("bearish", "FVG"),
    "swing_support": ("bullish", "SwingSR"), "swing_resistance": ("bearish", "SwingSR"),
}
POINT_FACTORS = {"CHoCH", "Sweep"}
RANGED_FACTORS = {"OB", "FVG", "SwingSR"}
ALL_FACTOR_TYPES = RANGED_FACTORS | POINT_FACTORS  # 5 total, matches "X/5" confidence framing

CONFLUENCE_ZONE_COLUMNS = [
    "symbol", "timeframe", "mode", "direction",
    "zone_core_top", "zone_core_bottom", "zone_full_top", "zone_full_bottom",
    "factor_count", "confidence_score", "factors",
    "created_at_bar", "last_factor_at_bar", "status", "resolved_at_bar",
]


def _events_from_htf(df: pd.DataFrame, symbol: str, timeframe: str) -> list:
    """Runs the three underlying engines and returns a flat list of
    factor events: {ts, direction, lo, hi, factor, detail}."""
    zone_eng = SMCZoneStateEngine()
    zones = zone_eng.detect_zones(df, symbol=symbol, timeframe=timeframe)

    struct_eng = SMCStructureEngine()
    structure = struct_eng.detect_bos_choch(df)
    choch = structure[structure["smc_structure_signal"].isin(["BULLISH_CHOCH", "BEARISH_CHOCH"])]

    sweep_eng = LiquiditySweepStateEngine()
    sweeps = sweep_eng.detect_sweeps(df, symbol=symbol, timeframe=timeframe)

    events = []
    for _, r in zones.iterrows():
        direction, factor = RANGED_ZONE_TYPES[r["zone_type"]]
        events.append(dict(
            ts=pd.Timestamp(r["created_at_bar"]), direction=direction,
            lo=float(r["zone_bottom"]), hi=float(r["zone_top"]), factor=factor,
            detail=dict(factor_type=factor, zone_type=r["zone_type"],
                        price_top=float(r["zone_top"]), price_bottom=float(r["zone_bottom"]),
                        formed_at_bar=str(r["created_at_bar"])),
        ))
    for _, r in choch.iterrows():
        direction = "bullish" if r["smc_structure_signal"] == "BULLISH_CHOCH" else "bearish"
        px = float(r["close_price"])
        events.append(dict(
            ts=pd.Timestamp(r["price_datetime"]), direction=direction, lo=px, hi=px, factor="CHoCH",
            detail=dict(factor_type="CHoCH", price_top=px, price_bottom=px,
                        formed_at_bar=str(r["price_datetime"])),
        ))
    for _, r in sweeps.iterrows():
        direction = r["direction"]
        px = float(r["swept_level_price"])
        events.append(dict(
            ts=pd.Timestamp(r["bar_datetime"]), direction=direction, lo=px, hi=px, factor="Sweep",
            detail=dict(factor_type="Sweep", sweep_type=r["sweep_type"], price_top=px, price_bottom=px,
                        formed_at_bar=str(r["bar_datetime"])),
        ))

    events.sort(key=lambda e: e["ts"])
    return events


def _price_overlap(a, b) -> bool:
    return a["lo"] <= b["hi"] and b["lo"] <= a["hi"]


def _cluster_events(events: list, bar_delta: pd.Timedelta, span_delta: pd.Timedelta) -> list:
    """Greedy single-pass clustering: same direction, overlapping price,
    within bar_delta of the cluster's most-recently-added member (matches
    the design-options prototype's clustering logic exactly -- see
    docs/DECISIONS.md), AND within span_delta of the cluster's FIRST
    member. The second bound exists because the first one alone lets a
    chain of factors arriving just under bar_delta apart drift a cluster
    arbitrarily far from where it started -- span_delta caps how long a
    single cluster is allowed to keep growing, independent of how tight
    each individual link is."""
    open_clusters = []
    for e in events:
        matched = None
        for c in open_clusters:
            if (c["direction"] == e["direction"] and (e["ts"] - c["last_ts"]) <= bar_delta
                    and (e["ts"] - c["first_ts"]) <= span_delta and _price_overlap(c, e)):
                matched = c
                break
        if matched:
            matched["lo"] = min(matched["lo"], e["lo"])
            matched["hi"] = max(matched["hi"], e["hi"])
            matched["last_ts"] = e["ts"]
            matched["factor_set"].add(e["factor"])
            matched["members"].append(e)
        else:
            open_clusters.append(dict(
                direction=e["direction"], lo=e["lo"], hi=e["hi"],
                first_ts=e["ts"], last_ts=e["ts"], factor_set={e["factor"]}, members=[e],
            ))
    return open_clusters


def _core_range(cluster: dict):
    """Intersection of the RANGED (FVG/OB/SwingSR) members only -- point
    events (CHoCH/Sweep) don't narrow it. Falls back to the cluster's full
    [lo, hi] if fewer than 2 ranged members contributed."""
    ranged = [m for m in cluster["members"] if m["factor"] in RANGED_FACTORS]
    if len(ranged) < 2:
        return cluster["lo"], cluster["hi"]
    core_lo = max(m["lo"] for m in ranged)
    core_hi = min(m["hi"] for m in ranged)
    if core_lo > core_hi:
        # ranged members don't all mutually overlap (only pairwise, via the
        # clustering chain) -- no single intersection exists; fall back to
        # full range rather than emit an inverted/empty core range.
        return cluster["lo"], cluster["hi"]
    return core_lo, core_hi


def _invalidation_bar(cluster: dict, direction: str, full_lo: float, full_hi: float,
                       df: pd.DataFrame) -> pd.Timestamp:
    """First bar, after the cluster formed, whose CLOSE breaks fully
    through zone_full_range on the adverse side -- same close-through rule
    zone_state.py uses for individual OB zones, applied to the confluence
    zone's own full range."""
    future = df[df["price_datetime"] > cluster["last_ts"]]
    if direction == "bullish":
        broken = future[future["close_price"] < full_lo]
    else:
        broken = future[future["close_price"] > full_hi]
    if broken.empty:
        return None
    return broken.iloc[0]["price_datetime"]


def detect_confluence_zones(df: pd.DataFrame, symbol: str, timeframe: str, mode: str) -> pd.DataFrame:
    """
    df: OHLC with price_datetime, open_price, high_price, low_price,
    close_price, sorted ascending (h4/h6/d1 -- resampled from MT5 h1 same
    as every other HTF consumer in this project).
    mode: 'mode_a_2factor' or 'mode_b_3factor'.
    Returns one row per qualifying confluence zone (CONFLUENCE_ZONE_COLUMNS).
    """
    if mode not in MODE_MIN_FACTORS:
        raise ValueError(f"mode must be one of {list(MODE_MIN_FACTORS)}, got {mode!r}")
    min_factors = MODE_MIN_FACTORS[mode]

    base = df.reset_index(drop=True).copy()
    base["price_datetime"] = pd.to_datetime(base["price_datetime"])

    events = _events_from_htf(base, symbol, timeframe)
    if not events:
        return pd.DataFrame(columns=CONFLUENCE_ZONE_COLUMNS)

    bar_span = (base["price_datetime"].iloc[1] - base["price_datetime"].iloc[0]) if len(base) > 1 else pd.Timedelta(hours=1)
    bar_delta = bar_span * CONFLUENCE_TIME_WINDOW_BARS
    span_delta = bar_span * CONFLUENCE_MAX_SPAN_BARS

    clusters = _cluster_events(events, bar_delta, span_delta)
    qualifying = [c for c in clusters if len(c["factor_set"]) >= min_factors]

    rows = []
    for c in qualifying:
        core_lo, core_hi = _core_range(c)
        inval_bar = _invalidation_bar(c, c["direction"], c["lo"], c["hi"], base)
        rows.append(dict(
            symbol=symbol, timeframe=timeframe, mode=mode, direction=c["direction"],
            zone_core_top=core_hi, zone_core_bottom=core_lo,
            zone_full_top=c["hi"], zone_full_bottom=c["lo"],
            factor_count=len(c["factor_set"]), confidence_score=f"{len(c['factor_set'])}/{len(ALL_FACTOR_TYPES)}",
            factors=[m["detail"] for m in c["members"]],
            created_at_bar=c["first_ts"], last_factor_at_bar=c["last_ts"],
            status="invalidated" if inval_bar is not None else "active",
            resolved_at_bar=inval_bar,
        ))
    return pd.DataFrame(rows, columns=CONFLUENCE_ZONE_COLUMNS)
