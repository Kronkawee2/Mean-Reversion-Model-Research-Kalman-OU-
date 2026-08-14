"""
Liquidity Sweep State Engine (Phase 3a addendum): persists Buy-Side/
Sell-Side Liquidity sweeps (BSL/SSL) against swing highs/lows, following
the same additive-module pattern as crt_state.py and zone_state.py. Does
not touch liquidity.py's SMCLiquidityEngine (still usable as-is elsewhere);
this module wraps its detect_liquidity_sweeps() output into
persistence-ready rows, reusing rather than re-deriving swing-pivot logic.

State model (deliberately NOT SMC's active/mitigated/invalidated, and NOT
even CRT's two-state pending/swept/expired): a liquidity sweep is a single
point-in-time event, fully resolved on the bar it occurs (the wick-through-
and-close-back-in pattern is confirmed the moment that bar closes — there is
no waiting/pending period the way an Asian-session level is watched across a
bounded window). The reference swing level itself has no expiration either:
it stays "live" as a target until a newer swing pivot replaces it (handled
by detect_swings' own ffill), so there's nothing analogous to CRT's
session-boundary expiry. One row per detected sweep event, matching
divergence_signals' point-in-time-event shape rather than either zone
table's lifecycle shape.

Causality: SMCLiquidityEngine.detect_liquidity_sweeps() already compares
bar i's high/low/close against the PRIOR bar's swing_high/swing_low
(sh[i-1]/sl[i-1]), and swing_high/swing_low are themselves only written
starting at their confirmation bar (pivot_window bars after the actual
pivot) by detect_swings — so no look-ahead is introduced here.
"""

import pandas as pd

from .liquidity import SMCLiquidityEngine
from .structure import SMCStructureEngine

LIQUIDITY_SWEEP_COLUMNS = [
    "symbol", "timeframe", "sweep_type", "direction", "swept_level_price", "bar_datetime",
]


class LiquiditySweepStateEngine:
    """Derives persistence-ready liquidity sweep event rows from OHLC data."""

    def detect_sweeps(self, df: pd.DataFrame, symbol: str, timeframe: str = "h1") -> pd.DataFrame:
        """
        df: OHLC with price_datetime, high_price, low_price, close_price,
        sorted ascending. Returns one row per detected sweep event.
        """
        if df.empty:
            return pd.DataFrame(columns=LIQUIDITY_SWEEP_COLUMNS)

        base = df.reset_index(drop=True).copy()
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])
        for col in ("high_price", "low_price", "close_price"):
            base[col] = base[col].astype(float)

        base = SMCStructureEngine().detect_swings(base)
        # sh_prev/sl_prev at row i are the same values detect_liquidity_sweeps
        # compares row i against internally — derived here (not modifying
        # liquidity.py) purely to capture which level got swept for
        # persistence, since detect_liquidity_sweeps only labels the event.
        base["_sh_prev"] = base["swing_high"].shift(1)
        base["_sl_prev"] = base["swing_low"].shift(1)

        swept = SMCLiquidityEngine().detect_liquidity_sweeps(base)

        rows = []
        for _, row in swept.iterrows():
            label = row["smc_liquidity_sweep"]
            if label is None:
                continue
            if label == "BSL_SWEEP_BEARISH":
                sweep_type, direction, level = "bsl", "bearish", row["_sh_prev"]
            else:  # SSL_SWEEP_BULLISH
                sweep_type, direction, level = "ssl", "bullish", row["_sl_prev"]
            rows.append({
                "symbol": symbol, "timeframe": timeframe,
                "sweep_type": sweep_type, "direction": direction,
                "swept_level_price": float(level), "bar_datetime": row["price_datetime"],
            })

        return pd.DataFrame(rows, columns=LIQUIDITY_SWEEP_COLUMNS) if rows else pd.DataFrame(columns=LIQUIDITY_SWEEP_COLUMNS)
