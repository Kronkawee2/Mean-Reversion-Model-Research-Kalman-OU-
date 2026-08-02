"""
Volatility Indicators: ATR (14) and Bollinger Bands (20, 2).

SOURCES & OFFICIAL REFERENCES:
- Wilder, J.W. (1978): ATR — New Concepts in Technical Trading Systems
- Bollinger, J. (2001): Bollinger on Bollinger Bands
- Investopedia ATR: https://www.investopedia.com/terms/a/atr.asp
- Investopedia BB: https://www.investopedia.com/terms/b/bollingerbands.asp
- Schwab Technical Analysis: https://www.schwab.com/learn/topic/technical-analysis
"""

import numpy as np
import pandas as pd


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's Average True Range (ATR).
    Formula:
      TR  = max(H - L,  |H - C_prev|,  |L - C_prev|)
      ATR = EMA(TR, period)  [Wilder's smoothing: alpha = 1/period]
    Use for: position sizing, stop-loss placement (e.g. 1.5×ATR below entry)
    """
    h = df["high_price"]
    l = df["low_price"]
    c_prev = df["close_price"].shift(1)

    tr = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean().round(6)


def calc_bollinger(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> pd.DataFrame:
    """
    Bollinger Bands (John Bollinger, 2001).
    Formula:
      Middle (SMA)  = SMA(Close, 20)
      Upper         = SMA + 2 * σ(Close, 20)
      Lower         = SMA - 2 * σ(Close, 20)
      %B            = (Close - Lower) / (Upper - Lower)
      Width         = (Upper - Lower) / Middle
    Squeeze: Width < 20-period min Width (low volatility → expansion incoming)
    """
    sma = series.rolling(window=period, min_periods=period).mean()
    std = series.rolling(window=period, min_periods=period).std()

    upper = sma + std_dev * std
    lower = sma - std_dev * std
    width = (upper - lower) / sma.replace(0, np.nan)
    pct_b = (series - lower) / (upper - lower).replace(0, np.nan)

    return pd.DataFrame({
        "bb_upper": upper.round(6),
        "bb_middle": sma.round(6),
        "bb_lower": lower.round(6),
        "bb_width": width.round(6),
        "bb_pct_b": pct_b.round(4),
    })


def add_volatility_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds ATR (14), Bollinger Bands (20, 2), and Volatility Regime classification.
    Volatility Regime:
      SQUEEZE : BB Width < rolling 20-period min Width
      LOW     : ATR % < 0.5%
      NORMAL  : 0.5% <= ATR % < 1.5%
      HIGH    : ATR % >= 1.5%
    ATR % = ATR / Close (normalized)
    """
    res = df.copy()
    c = res["close_price"]

    res["atr_14"] = calc_atr(res, 14)
    res["atr_pct"] = (res["atr_14"] / c.replace(0, np.nan)).round(5)

    bb = calc_bollinger(c, 20, 2.0)
    res["bb_upper"] = bb["bb_upper"]
    res["bb_middle"] = bb["bb_middle"]
    res["bb_lower"] = bb["bb_lower"]
    res["bb_width"] = bb["bb_width"]
    res["bb_pct_b"] = bb["bb_pct_b"]

    bb_width_min = bb["bb_width"].rolling(20).min()

    def _regime(row):
        atr_p = row.get("atr_pct", np.nan)
        bw = row.get("bb_width", np.nan)
        bw_min = bb_width_min.loc[row.name] if row.name in bb_width_min.index else np.nan

        if not np.isnan(bw) and not np.isnan(bw_min) and bw <= bw_min:
            return "SQUEEZE"
        if np.isnan(atr_p):
            return "NORMAL"
        if atr_p < 0.005:
            return "LOW"
        if atr_p >= 0.015:
            return "HIGH"
        return "NORMAL"

    res["vol_regime"] = res.apply(_regime, axis=1)
    return res
