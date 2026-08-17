"""
Technical Divergence Engine: turns the pivot/classification primitives
already in detection.py into persisted, structured divergence records
with full pivot-pair detail. Category 2 (Technical) of the divergence
matrix is now complete across all four indicators: RSI (Phase 2e), OBV
(Phase 2f), Stochastic %K and CCI (Phase 2g) — all Regular + Hidden,
Bullish + Bearish.

RSI's first pass wired up only Regular Bullish/Bearish (reversal); a
second pass added Hidden Bullish/Bearish (continuation) —
classify_divergence() already computed HIDDEN_* labels correctly (with
the pivot_type disambiguation that fixed a real Regular-vs-Hidden
ambiguity bug caught in the first pass's tests), it just wasn't
persisted yet. detect() now emits both classes for every indicator,
distinguished by the `divergence_class` column ('regular'/'hidden') added
to divergence_signals for exactly this reason — direction
('bullish'/'bearish') alone can't distinguish a REGULAR_BULLISH from a
HIDDEN_BULLISH, since both share direction='bullish' but mean opposite
things (reversal vs continuation). OBV, Stochastic, and CCI each needed
zero framework changes — the whole point of building it indicator-
agnostic was that adding a new indicator is a call-site change
(indicator_col/divergence_type) in the caller, not new logic here; the
OBV pass proved this, and Stochastic/CCI confirm it holds.

Explicitly deferred, not attempted here:
  - All inter-market/macro divergence models (detection.py's
    detect_intermarket_divergence/detect_cot_divergence already exist for
    that piece and are untouched by this module — cross-database
    alignment is a different problem, deferred)
  - MTF Alignment Divergence (HTF Hidden Divergence confluence with LTF
    Regular Divergence, indicator-matched) — DESIGNED, EMPIRICALLY TESTED,
    NOT BUILT. Before implementing the pipeline, an empirical pre-check
    (same discipline as every timeframe-specific constant in this
    project) compared the real HTF-hidden/LTF-regular match rate against
    a random-null baseline across window candidates 5h-720h, for RSI/OBV/
    Stochastic/CCI on gold plus RSI on EURUSD (5 combinations). NONE
    showed a meaningful positive lift over random chance at any
    operationally useful window — real match rates were AT OR BELOW the
    null baseline from 5h out to ~320h in every case, only converging
    near-zero-lift at the trivially wide 480-720h (20-30 day) range where
    event density alone makes overlap nearly inevitable regardless of any
    real timing relationship. This is a genuine negative finding, not an
    unfinished feature — the divergence matrix is closed at 11/12 models
    with this one formally deferred (see docs/DECISIONS.md). The test
    itself is reusable: scripts/diagnostic/test_mtf_alignment_divergence_lift.py
    (kept for re-running if more history accumulates or a different
    symbol/indicator/methodology is worth checking later).

Design (reusable across indicators): `find_price_pivots` (detection.py)
does the indicator-agnostic pivot-finding — price pivots only, with the
indicator's value sampled at those same pivot bars (the standard way
divergence is read; see that function's docstring for why). This module
adds indicator-agnostic classification (`classify_divergence`) and turns
matched pivot pairs into one row per confirmed divergence, with both
pivot bars' timestamp/price/indicator value — the shape needed for
persistence, which detect_technical_divergence's single annotated-column
output doesn't carry.
"""

import pandas as pd

from .detection import find_price_pivots

DIVERGENCE_SIGNAL_COLUMNS = [
    "symbol", "timeframe", "bar_datetime", "divergence_type", "divergence_class", "direction",
    "prev_pivot_datetime", "prev_pivot_price", "prev_pivot_indicator",
    "curr_pivot_datetime", "curr_pivot_price", "curr_pivot_indicator",
]

# label (from classify_divergence) -> (divergence_class, direction)
LABEL_TO_CLASS_DIRECTION = {
    "REGULAR_BULLISH": ("regular", "bullish"),
    "REGULAR_BEARISH": ("regular", "bearish"),
    "HIDDEN_BULLISH": ("hidden", "bullish"),
    "HIDDEN_BEARISH": ("hidden", "bearish"),
}


def classify_divergence(p_prev: float, p_curr: float, i_prev: float, i_curr: float, pivot_type: str) -> str | None:
    """
    Indicator-agnostic classification of a price-pivot pair (prev -> curr)
    against the indicator's value at those same two pivots.
    Source: CFI & Investopedia Technical Divergence Definitions (same
    definitions detection.py's detect_technical_divergence uses).

    pivot_type must be 'low' or 'high' — the (price direction, indicator
    direction) pattern is genuinely ambiguous without it: "price up,
    indicator down" means HIDDEN_BULLISH on a low-pivot pair but
    REGULAR_BEARISH on a high-pivot pair, and there is no way to tell
    those apart from the four numbers alone.

    pivot_type='low' (bullish side):
      REGULAR_BULLISH (Reversal):     Price Lower Low,  Indicator Higher Low
      HIDDEN_BULLISH (Continuation):  Price Higher Low, Indicator Lower Low
    pivot_type='high' (bearish side):
      REGULAR_BEARISH (Reversal):     Price Higher High, Indicator Lower High
      HIDDEN_BEARISH (Continuation):  Price Lower High,  Indicator Higher High
    """
    if pivot_type == "low":
        if p_curr < p_prev and i_curr > i_prev:
            return "REGULAR_BULLISH"
        if p_curr > p_prev and i_curr < i_prev:
            return "HIDDEN_BULLISH"
    elif pivot_type == "high":
        if p_curr > p_prev and i_curr < i_prev:
            return "REGULAR_BEARISH"
        if p_curr < p_prev and i_curr > i_prev:
            return "HIDDEN_BEARISH"
    else:
        raise ValueError(f"pivot_type must be 'low' or 'high', got {pivot_type!r}")
    return None


class TechnicalDivergenceEngine:
    """Detects and persists RSI Regular + Hidden Bullish/Bearish divergence signals from price+indicator pivots."""

    def __init__(self, pivot_window: int = 3):
        self.pivot_window = pivot_window

    def detect(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        indicator_col: str = "rsi_14",
        divergence_type: str = "rsi",
    ) -> pd.DataFrame:
        """
        df: merged price+indicator data with price_datetime, close_price,
        and `indicator_col`, sorted ascending. Returns one row per
        confirmed divergence — both Regular (reversal) and Hidden
        (continuation), distinguished by the `divergence_class` column.
        """
        if df.empty or indicator_col not in df.columns:
            return pd.DataFrame(columns=DIVERGENCE_SIGNAL_COLUMNS)

        base = df.reset_index(drop=True).copy()
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])
        base = base.dropna(subset=["close_price", indicator_col]).reset_index(drop=True)
        if base.empty:
            return pd.DataFrame(columns=DIVERGENCE_SIGNAL_COLUMNS)

        prices = base["close_price"].values
        indicators = base[indicator_col].values
        datetimes = base["price_datetime"].values
        n = len(base)
        w = self.pivot_window

        pivots_low, pivots_high = find_price_pivots(prices, indicators, w)

        rows = []

        # Low-pivot pairs -> bullish side (Regular Bullish or Hidden Bullish)
        for k in range(1, len(pivots_low)):
            idx_prev, p_prev, i_prev = pivots_low[k - 1]
            idx_curr, p_curr, i_curr = pivots_low[k]

            signal_idx = idx_curr + w
            if signal_idx >= n:
                continue

            label = classify_divergence(p_prev, p_curr, i_prev, i_curr, pivot_type="low")
            if label not in LABEL_TO_CLASS_DIRECTION:
                continue
            div_class, direction = LABEL_TO_CLASS_DIRECTION[label]

            rows.append({
                "symbol": symbol, "timeframe": timeframe,
                "bar_datetime": pd.Timestamp(datetimes[signal_idx]),
                "divergence_type": divergence_type, "divergence_class": div_class, "direction": direction,
                "prev_pivot_datetime": pd.Timestamp(datetimes[idx_prev]),
                "prev_pivot_price": float(p_prev), "prev_pivot_indicator": float(i_prev),
                "curr_pivot_datetime": pd.Timestamp(datetimes[idx_curr]),
                "curr_pivot_price": float(p_curr), "curr_pivot_indicator": float(i_curr),
            })

        # High-pivot pairs -> bearish side (Regular Bearish or Hidden Bearish)
        for k in range(1, len(pivots_high)):
            idx_prev, p_prev, i_prev = pivots_high[k - 1]
            idx_curr, p_curr, i_curr = pivots_high[k]

            signal_idx = idx_curr + w
            if signal_idx >= n:
                continue

            label = classify_divergence(p_prev, p_curr, i_prev, i_curr, pivot_type="high")
            if label not in LABEL_TO_CLASS_DIRECTION:
                continue
            div_class, direction = LABEL_TO_CLASS_DIRECTION[label]

            rows.append({
                "symbol": symbol, "timeframe": timeframe,
                "bar_datetime": pd.Timestamp(datetimes[signal_idx]),
                "divergence_type": divergence_type, "divergence_class": div_class, "direction": direction,
                "prev_pivot_datetime": pd.Timestamp(datetimes[idx_prev]),
                "prev_pivot_price": float(p_prev), "prev_pivot_indicator": float(i_prev),
                "curr_pivot_datetime": pd.Timestamp(datetimes[idx_curr]),
                "curr_pivot_price": float(p_curr), "curr_pivot_indicator": float(i_curr),
            })

        if not rows:
            return pd.DataFrame(columns=DIVERGENCE_SIGNAL_COLUMNS)
        return pd.DataFrame(rows, columns=DIVERGENCE_SIGNAL_COLUMNS).sort_values("bar_datetime").reset_index(drop=True)
