"""
LTF Trigger Engine (Pass 2 of strategies/): confirms an actual entry signal
when price enters an active HTF (h1) SMC zone and LTF structure confirms a
reversal in the zone's expected direction.

Two selectable confirmation modes, not one hardcoded choice (confirmed with
the user before building):
  - 'choch_only': zone touch + a CHoCH in the zone's expected direction,
    within CONFIRMATION_WINDOW_BARS of each other (order-agnostic -- CHoCH
    can confirm after the touch, or the touch can be a retest of structure
    that already flipped; both are legitimate SMC patterns and this mode is
    meant to be the permissive one). Faster, more signals, less strict.
  - 'choch_sweep': everything choch_only requires, PLUS a liquidity sweep
    (in the zone's expected direction) that precedes the CHoCH (sweep bar
    <= CHoCH bar), both within the same window. Matches the standard SMC
    narrative -- sweep = stop-hunt/trap, CHoCH = confirmation the trap
    worked. Stricter, fewer signals, higher conviction per signal.

Reuses SMCStructureEngine.detect_bos_choch() and LiquiditySweepStateEngine
as-is on the LTF series (m15 default, m5 also supported via ltf_timeframe)
-- no new detection primitives here, this module is pure orchestration
over existing causal building blocks, following the same additive-module
pattern as every other engine in this package.

CONFIRMATION_WINDOW_BARS = 20 (LTF bars, by bar-position not wall-clock
time, so weekend gaps don't distort it) matches this project's existing
lookback convention (divergence, liquidity sweep) for consistency. Flagged
explicitly: unlike SMC's 720-bar recency window, this has NOT been
validated against real LTF signal data yet, since none existed before this
pass -- treat as a starting point subject to the same kind of real-data
review the SMC window got, not a settled constant.

CHoCH direction must match the zone's expected reaction direction: a
bullish zone (order_block_bullish/fvg_bullish/swing_support) only confirms
on BULLISH_CHOCH; a bearish zone only confirms on BEARISH_CHOCH. A CHoCH in
the "wrong" direction relative to a nearby zone is unrelated structure, not
a confirmation of that zone.

Each trigger row's true actionable moment is `confirmed_at_bar` --
max(touch_bar, choch_bar, sweep_bar) -- since a live system only knows all
required conditions are satisfied once the LAST of them has actually
happened, regardless of which one is stored as "the" touch or CHoCH bar.
"""

import numpy as np
import pandas as pd

from analysis.smc_crt.structure import SMCStructureEngine
from analysis.smc_crt.liquidity_state import LiquiditySweepStateEngine

CONFIRMATION_WINDOW_BARS = 20

BULLISH_ZONE_TYPES = {"order_block_bullish", "fvg_bullish", "swing_support"}
BEARISH_ZONE_TYPES = {"order_block_bearish", "fvg_bearish", "swing_resistance"}

MODES = ("choch_only", "choch_sweep")

CHOCH_LABEL_FOR_DIRECTION = {"bullish": "BULLISH_CHOCH", "bearish": "BEARISH_CHOCH"}

LTF_TRIGGER_COLUMNS = [
    "symbol", "ltf_timeframe", "mode", "direction",
    "htf_zone_type", "htf_zone_top", "htf_zone_bottom", "htf_zone_created_at_bar",
    "touch_bar_datetime", "choch_bar_datetime", "sweep_bar_datetime", "sweep_type",
    "confirmed_at_bar",
]


def _zone_direction(zone_type: str):
    if zone_type in BULLISH_ZONE_TYPES:
        return "bullish"
    if zone_type in BEARISH_ZONE_TYPES:
        return "bearish"
    return None


class LTFTriggerEngine:
    """Confirms LTF entry triggers against active HTF SMC zones, in two selectable confirmation modes."""

    def __init__(self, pivot_window: int = 3, confirmation_window_bars: int = CONFIRMATION_WINDOW_BARS):
        self.pivot_window = pivot_window
        self.confirmation_window_bars = confirmation_window_bars

    def compute_triggers(
        self,
        ltf_bars: pd.DataFrame,
        htf_zones: pd.DataFrame,
        symbol: str,
        ltf_timeframe: str = "m15",
        mode: str = "choch_only",
    ) -> pd.DataFrame:
        """
        ltf_bars: price_datetime, high_price, low_price, close_price (raw m5/m15), sorted ascending.
        htf_zones: zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar
                   (curated.smc_signals, timeframe='h1'). No `state` filter -- see
                   htf_bias_engine.py for why filtering on a zone's terminal state
                   would wrongly exclude its genuine causal active lifetime.
        Returns one row per confirmed trigger (LTF_TRIGGER_COLUMNS).
        """
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        if ltf_bars.empty or htf_zones.empty:
            return pd.DataFrame(columns=LTF_TRIGGER_COLUMNS)

        base = ltf_bars.reset_index(drop=True).copy()
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])
        for col in ("high_price", "low_price", "close_price"):
            base[col] = base[col].astype(float)

        structure = SMCStructureEngine(pivot_window=self.pivot_window).detect_bos_choch(base)
        choch_events = structure[structure["smc_structure_signal"].isin(["BULLISH_CHOCH", "BEARISH_CHOCH"])]

        sweeps = pd.DataFrame(columns=["bar_datetime", "direction", "sweep_type"])
        if mode == "choch_sweep":
            sweeps = LiquiditySweepStateEngine().detect_sweeps(base, symbol=symbol, timeframe=ltf_timeframe)

        bar_times = base["price_datetime"].values
        lows = base["low_price"].values
        highs = base["high_price"].values
        n = len(base)
        w = self.confirmation_window_bars

        choch_idx_by_row = {
            idx: np.searchsorted(bar_times, np.datetime64(row["price_datetime"]))
            for idx, row in choch_events.iterrows()
        }
        sweep_idx = (
            np.searchsorted(bar_times, sweeps["bar_datetime"].values.astype("datetime64[ns]"))
            if not sweeps.empty else np.array([], dtype=int)
        )

        rows = []
        for _, zone in htf_zones.iterrows():
            direction = _zone_direction(zone["zone_type"])
            if direction is None:
                continue

            created = np.datetime64(zone["created_at_bar"])
            invalidated = zone["invalidated_at_bar"]
            invalidated = np.datetime64(invalidated) if pd.notnull(invalidated) else None

            active_mask = bar_times >= created
            if invalidated is not None:
                active_mask &= bar_times < invalidated

            # A touch must occur only after the zone's own formation h1 bar has
            # fully closed -- otherwise an LTF sub-bar inside that same h1 hour
            # trivially "touches" the zone, since the zone's top/bottom were
            # derived from that exact candle's own high/low. That's re-detecting
            # the formation candle, not a genuine later revisit. Found via real
            # data: 36.2% of choch_only signals had touch_bar_datetime inside the
            # zone's own formation hour (32.4% exactly equal to it).
            formation_closed = created + np.timedelta64(1, "h")
            touch_mask = (
                active_mask & (bar_times >= formation_closed)
                & (lows <= float(zone["zone_top"])) & (highs >= float(zone["zone_bottom"]))
            )
            touch_indices = np.where(touch_mask)[0]
            if len(touch_indices) == 0:
                continue

            want_label = CHOCH_LABEL_FOR_DIRECTION[direction]
            zone_choch = choch_events[choch_events["smc_structure_signal"] == want_label]

            for choch_row_idx, choch_row in zone_choch.iterrows():
                choch_idx = choch_idx_by_row[choch_row_idx]
                nearby = touch_indices[np.abs(touch_indices - choch_idx) <= w]
                if len(nearby) == 0:
                    continue

                sweep_bar = None
                sweep_type = None
                if mode == "choch_sweep":
                    if sweeps.empty:
                        continue
                    dir_mask = sweeps["direction"].values == direction
                    order_mask = (sweep_idx <= choch_idx) & (choch_idx - sweep_idx <= w)
                    qualifying = np.where(dir_mask & order_mask)[0]
                    if len(qualifying) == 0:
                        continue
                    best = qualifying[np.argmax(sweep_idx[qualifying])]  # most recent qualifying sweep before CHoCH
                    sweep_bar = sweeps["bar_datetime"].iloc[best]
                    sweep_type = sweeps["sweep_type"].iloc[best]

                touch_bar = base["price_datetime"].iloc[nearby[0]]  # earliest qualifying touch
                choch_bar = choch_row["price_datetime"]
                confirmed_at = max(t for t in (touch_bar, choch_bar, sweep_bar) if t is not None)

                rows.append({
                    "symbol": symbol, "ltf_timeframe": ltf_timeframe, "mode": mode, "direction": direction,
                    "htf_zone_type": zone["zone_type"],
                    "htf_zone_top": float(zone["zone_top"]), "htf_zone_bottom": float(zone["zone_bottom"]),
                    "htf_zone_created_at_bar": zone["created_at_bar"],
                    "touch_bar_datetime": touch_bar, "choch_bar_datetime": choch_bar,
                    "sweep_bar_datetime": sweep_bar, "sweep_type": sweep_type,
                    "confirmed_at_bar": confirmed_at,
                })

        if not rows:
            return pd.DataFrame(columns=LTF_TRIGGER_COLUMNS)

        out = pd.DataFrame(rows, columns=LTF_TRIGGER_COLUMNS)
        out = out.drop_duplicates(
            subset=["symbol", "ltf_timeframe", "mode", "htf_zone_type", "htf_zone_created_at_bar",
                    "touch_bar_datetime", "choch_bar_datetime"]
        ).sort_values("confirmed_at_bar").reset_index(drop=True)
        return out
