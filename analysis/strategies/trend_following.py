"""
Donchian-channel breakout trend-following (the classic "Turtle" system
shape), added as a second strategy family after the Kalman/OU mean-
reversion engine (kalman_mean_reversion.py) failed to show a statistically
significant edge on any tested symbol/timeframe under rolling walk-forward
validation (see scripts/research/RESULTS.md experiment 22). NDX100 in
particular was flagged there as looking trend-dominant (waterfall-style
drawdowns, non-stationary trade counts) -- structurally the wrong fit for
mean-reversion. This module is the opposite bet: instead of fading a move
away from a rolling mean, it buys strength / sells weakness once price
clears its own recent range, betting the move continues rather than
reverts.

Core idea: track the rolling N-bar high/low of CLOSE (not high/low of the
bar -- keeps the band computed on the same series being tested against,
avoids intrabar noise inflating the band). Enter long when price closes
above the rolling high, short when it closes below the rolling low.
Exit on a SHORTER rolling band crossing back the other way (the classic
Turtle two-window shape: a wide entry window filters out minor noise, a
narrower exit window locks in the reversal signal faster than waiting for
a full round-trip back through the entry band).
"""

import numpy as np
import pandas as pd


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's ATR, same implementation as kalman_mean_reversion.py's
    private helper -- duplicated rather than imported to keep the two
    strategy modules independent of each other."""
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.nanmax(np.vstack([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ]), axis=0)
    return pd.Series(tr).ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()


def run_trend_following(
    bar_datetime: pd.Series,
    close: pd.Series,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    entry_window: int = 55,
    exit_window: int = 20,
    trend_filter_ema: int | None = None,
    atr_period: int = 14,
    atr_stop_mult: float | None = None,
    side: str = "both",
) -> pd.DataFrame:
    """Bar-by-bar Donchian breakout signal generator, same output shape as
    kalman_mean_reversion.run_mean_reversion() (bar_datetime, close,
    signal) so it plugs into the same sim_pnl()/run_cfg() trade-extraction
    helpers used by scripts/research/kalman_walkforward.py and
    rolling_wfo.py without modification.

    entry_window / exit_window: rolling N-bar high/low of CLOSE, both
    shifted by 1 bar so the band used to judge bar t never includes bar
    t's own close (causal). entry_window must exceed exit_window for the
    two-window shape to do anything (a wide entry filter, a narrower exit
    trigger) -- not enforced here, but a config with exit_window >=
    entry_window degenerates toward "exit almost immediately."

    trend_filter_ema: if set, blocks entries against the prevailing trend
    -- longs only allowed when close > EMA(trend_filter_ema), shorts only
    when close < EMA(trend_filter_ema). None = off (take every breakout
    regardless of the longer-term trend).

    atr_stop_mult / atr_period: requires high/low. Kills the position if
    adverse excursion from entry exceeds atr_stop_mult * ATR(atr_period)
    -- a hard risk floor under the band-based exit, since a breakout that
    immediately reverses hard (failed breakout) can otherwise run all the
    way to the exit band before this system reacts.

    side: "both" (default) / "long_only" / "short_only".

    Returns one row per input bar (NaN columns before entry_window bars
    have accumulated) with entry_high/entry_low/exit_high/exit_low band
    values and a `signal` column: 'long'/'short' on entry, 'close_long'/
    'close_short' on the opposite-band exit, 'atr_stop_long'/
    'atr_stop_short' on the risk-control exit.
    """
    if side not in ("both", "long_only", "short_only"):
        raise ValueError(f"side must be 'both'/'long_only'/'short_only', got {side!r}")

    n = len(close)
    closes = close.to_numpy(dtype=float)
    highs = high.to_numpy(dtype=float) if high is not None else None
    lows = low.to_numpy(dtype=float) if low is not None else None

    close_s = pd.Series(closes)
    entry_high = close_s.rolling(entry_window).max().shift(1).to_numpy()
    entry_low = close_s.rolling(entry_window).min().shift(1).to_numpy()
    exit_high = close_s.rolling(exit_window).max().shift(1).to_numpy()
    exit_low = close_s.rolling(exit_window).min().shift(1).to_numpy()
    ema_filter = close_s.ewm(span=trend_filter_ema, adjust=False).mean().to_numpy() if trend_filter_ema else None
    atr = _atr(highs, lows, closes, atr_period) if (atr_stop_mult and highs is not None) else None

    signals = [None] * n
    position = 0  # 1 long, -1 short, 0 flat
    entry_price = None
    warmup = max(entry_window, exit_window, trend_filter_ema or 0)

    for t in range(n):
        if t < warmup or not np.isfinite(entry_high[t]):
            continue
        price = closes[t]

        if position != 0:
            if atr_stop_mult and atr is not None and np.isfinite(atr[t]):
                adverse = (entry_price - price) if position == 1 else (price - entry_price)
                if adverse >= atr_stop_mult * atr[t]:
                    signals[t] = "atr_stop_long" if position == 1 else "atr_stop_short"
                    position, entry_price = 0, None
                    continue
            if position == 1 and price < exit_low[t]:
                signals[t] = "close_long"
                position, entry_price = 0, None
                continue
            if position == -1 and price > exit_high[t]:
                signals[t] = "close_short"
                position, entry_price = 0, None
                continue

        if position == 0:
            trend_ok_long = ema_filter is None or price > ema_filter[t]
            trend_ok_short = ema_filter is None or price < ema_filter[t]
            if side != "short_only" and price > entry_high[t] and trend_ok_long:
                position, entry_price = 1, price
                signals[t] = "long"
            elif side != "long_only" and price < entry_low[t] and trend_ok_short:
                position, entry_price = -1, price
                signals[t] = "short"

    return pd.DataFrame({
        "bar_datetime": bar_datetime.to_numpy(),
        "close": closes,
        "entry_high": entry_high,
        "entry_low": entry_low,
        "exit_high": exit_high,
        "exit_low": exit_low,
        "signal": signals,
    })
