"""
SMC Zone-State Engine (Phase 2a): turns the existing candle-pattern detectors
(BOS/CHoCH structure, Order Blocks, FVG) into persistent zones with an
active -> mitigated -> invalidated lifecycle, per the engineering brief's
zone-state model. Reuses SMCStructureEngine/SMCOrderBlockEngine/
SMCImbalanceEngine for pattern detection (unchanged) and adds the state
machine on top — it does not replace or alter those modules' own
wick-touch-based `smc_*_mitigated` columns, which scoring.py still uses as
before.

Scope (Phase 2a only): order blocks, FVGs, swing support/resistance zones.
Liquidity sweeps (BSL/SSL) are explicitly deferred to a later pass, not
attempted here.

Invalidation rules (exact, coded — not eyeballed):
  - FVG: invalidated when a candle CLOSES beyond FVG_INVALIDATION_PCT (default
    0.5 = 50%) of the gap, in the direction that negates the FVG. Mitigated
    (a weaker, non-terminal state) when price wicks back into the gap without
    yet closing past the threshold.
  - Order Block: invalidated when a candle CLOSES fully through the OB's
    opposite boundary (below the bottom for a bullish OB, above the top for
    a bearish OB). Mitigated when price wicks into the OB body without a
    close-through.
  - Swing support/resistance: invalidated only on two CONSECUTIVE candle
    closes beyond the zone (confirmed follow-through) — a single close
    beyond the zone that gets immediately reclaimed the next bar does NOT
    invalidate it. This is stricter than the FVG/OB rules on purpose, since
    a swing zone has no natural "opposite boundary" and a single-bar spike
    is common noise at S/R levels. Mitigated when price wicks into the zone
    without that two-bar confirmation.
"""

import pandas as pd

from .structure import SMCStructureEngine
from .order_block import SMCOrderBlockEngine
from .imbalance import SMCImbalanceEngine

FVG_INVALIDATION_PCT = 0.5

ZONE_COLUMNS = [
    "symbol", "timeframe", "zone_type", "zone_top", "zone_bottom",
    "state", "created_at_bar", "mitigated_at_bar", "invalidated_at_bar",
]


class SMCZoneStateEngine:
    """Detects OB/FVG/swing zones and evolves their active/mitigated/invalidated state."""

    def __init__(self, pivot_window: int = 3):
        self.pivot_window = pivot_window
        self.struct_engine = SMCStructureEngine(pivot_window=pivot_window)
        self.ob_engine = SMCOrderBlockEngine()
        self.imb_engine = SMCImbalanceEngine()

    def detect_zones(self, df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        df: OHLCV with price_datetime, open_price, high_price, low_price,
        close_price, sorted ascending. Returns one row per zone.
        """
        if df.empty:
            return pd.DataFrame(columns=ZONE_COLUMNS)

        base = df.reset_index(drop=True)
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])

        struct = self.struct_engine.detect_bos_choch(base)
        ob = self.ob_engine.detect_order_blocks(struct)
        fvg = self.imb_engine.detect_fvg(ob)

        zones = []
        zones += self._order_block_zones(fvg)
        zones += self._fvg_zones(fvg)
        zones += self._swing_zones(struct)

        for z in zones:
            z["symbol"] = symbol
            z["timeframe"] = timeframe

        if not zones:
            return pd.DataFrame(columns=ZONE_COLUMNS)
        return pd.DataFrame(zones)[ZONE_COLUMNS]

    # ------------------------------------------------------------------
    # Zone extraction (raw detection, initial state='active')
    # ------------------------------------------------------------------

    def _order_block_zones(self, df: pd.DataFrame) -> list:
        zones = []
        for i in range(len(df)):
            ob_type = df["smc_ob_type"].iloc[i]
            if ob_type is None:
                continue
            top = float(df["smc_ob_top"].iloc[i])
            bottom = float(df["smc_ob_bottom"].iloc[i])
            created_at = df["price_datetime"].iloc[i]
            zone_type = "order_block_bullish" if ob_type == "BULLISH_OB" else "order_block_bearish"
            state, mit_at, inv_at = self._evolve_order_block(df, i, zone_type, top, bottom)
            zones.append({
                "zone_type": zone_type, "zone_top": top, "zone_bottom": bottom,
                "created_at_bar": created_at, "state": state,
                "mitigated_at_bar": mit_at, "invalidated_at_bar": inv_at,
            })
        return zones

    def _fvg_zones(self, df: pd.DataFrame) -> list:
        zones = []
        for i in range(len(df)):
            fvg_type = df["smc_fvg_type"].iloc[i]
            if fvg_type is None:
                continue
            top = float(df["smc_fvg_top"].iloc[i])
            bottom = float(df["smc_fvg_bottom"].iloc[i])
            created_at = df["price_datetime"].iloc[i]
            zone_type = "fvg_bullish" if fvg_type == "BULLISH_FVG" else "fvg_bearish"
            state, mit_at, inv_at = self._evolve_fvg(df, i, zone_type, top, bottom)
            zones.append({
                "zone_type": zone_type, "zone_top": top, "zone_bottom": bottom,
                "created_at_bar": created_at, "state": state,
                "mitigated_at_bar": mit_at, "invalidated_at_bar": inv_at,
            })
        return zones

    def _swing_zones(self, df: pd.DataFrame) -> list:
        zones = []
        w = self.pivot_window
        n = len(df)
        for conf_idx in range(n):
            pivot_idx = conf_idx - w
            if pivot_idx < 0:
                continue

            if bool(df["is_swing_high"].iloc[conf_idx]):
                top = float(df["high_price"].iloc[pivot_idx])
                bottom = float(df["low_price"].iloc[pivot_idx])
                created_at = df["price_datetime"].iloc[pivot_idx]
                state, mit_at, inv_at = self._evolve_swing(df, pivot_idx, "swing_resistance", top, bottom)
                zones.append({
                    "zone_type": "swing_resistance", "zone_top": top, "zone_bottom": bottom,
                    "created_at_bar": created_at, "state": state,
                    "mitigated_at_bar": mit_at, "invalidated_at_bar": inv_at,
                })

            if bool(df["is_swing_low"].iloc[conf_idx]):
                top = float(df["high_price"].iloc[pivot_idx])
                bottom = float(df["low_price"].iloc[pivot_idx])
                created_at = df["price_datetime"].iloc[pivot_idx]
                state, mit_at, inv_at = self._evolve_swing(df, pivot_idx, "swing_support", top, bottom)
                zones.append({
                    "zone_type": "swing_support", "zone_top": top, "zone_bottom": bottom,
                    "created_at_bar": created_at, "state": state,
                    "mitigated_at_bar": mit_at, "invalidated_at_bar": inv_at,
                })
        return zones

    # ------------------------------------------------------------------
    # State machines (scan forward from the zone's own bar)
    # ------------------------------------------------------------------

    def _evolve_order_block(self, df, created_idx, zone_type, top, bottom):
        state, mit_at, inv_at = "active", None, None
        bullish = zone_type == "order_block_bullish"

        for j in range(created_idx + 1, len(df)):
            low_j = df["low_price"].iloc[j]
            high_j = df["high_price"].iloc[j]
            close_j = df["close_price"].iloc[j]
            ts = df["price_datetime"].iloc[j]

            if bullish:
                closed_through = close_j < bottom
            else:
                closed_through = close_j > top

            if closed_through:
                state, inv_at = "invalidated", ts
                break

            touched = (low_j <= top and high_j >= bottom)
            if touched and state == "active":
                state, mit_at = "mitigated", ts

        return state, mit_at, inv_at

    def _evolve_fvg(self, df, created_idx, zone_type, top, bottom):
        state, mit_at, inv_at = "active", None, None
        bullish = zone_type == "fvg_bullish"
        midpoint = bottom + FVG_INVALIDATION_PCT * (top - bottom)

        for j in range(created_idx + 1, len(df)):
            low_j = df["low_price"].iloc[j]
            high_j = df["high_price"].iloc[j]
            close_j = df["close_price"].iloc[j]
            ts = df["price_datetime"].iloc[j]

            if bullish:
                closed_through = close_j < midpoint
            else:
                closed_through = close_j > midpoint

            if closed_through:
                state, inv_at = "invalidated", ts
                break

            touched = (low_j <= top and high_j >= bottom)
            if touched and state == "active":
                state, mit_at = "mitigated", ts

        return state, mit_at, inv_at

    def _evolve_swing(self, df, created_idx, zone_type, top, bottom):
        state, mit_at, inv_at = "active", None, None
        resistance = zone_type == "swing_resistance"
        n = len(df)

        j = created_idx + 1
        while j < n:
            low_j = df["low_price"].iloc[j]
            high_j = df["high_price"].iloc[j]
            close_j = df["close_price"].iloc[j]
            ts = df["price_datetime"].iloc[j]

            breached = (close_j > top) if resistance else (close_j < bottom)
            if breached:
                if j + 1 < n:
                    close_next = df["close_price"].iloc[j + 1]
                    ts_next = df["price_datetime"].iloc[j + 1]
                    confirmed = (close_next > top) if resistance else (close_next < bottom)
                    if confirmed:
                        state, inv_at = "invalidated", ts_next
                        break
                    # single-bar spike reclaimed next bar: not invalidated, keep scanning
                # last bar breached with no follow-up bar to confirm: leave as-is

            touched = (low_j <= top and high_j >= bottom)
            if touched and state == "active":
                state, mit_at = "mitigated", ts

            j += 1

        return state, mit_at, inv_at
