"""
Momentum Indicators: RSI (14) and MACD (12, 26, 9).

SOURCES & OFFICIAL REFERENCES:
- Wilder, J.W. (1978): RSI — New Concepts in Technical Trading Systems
- Investopedia RSI: https://www.investopedia.com/terms/r/rsi.asp
- Investopedia MACD: https://www.investopedia.com/terms/m/macd.asp
- Axi Best Indicators: https://www.axi.com/int/blog/education/trading-indicators
"""

import numpy as np
import pandas as pd


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's Relative Strength Index (RSI).
    Formula:
      RS  = AvgGain(period) / AvgLoss(period)   [Wilder Smoothed EMA]
      RSI = 100 - (100 / (1 + RS))
    Overbought: RSI > 70  |  Oversold: RSI < 30
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).round(3)


def calc_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """
    Moving Average Convergence Divergence (MACD).
    Formula:
      MACD Line    = EMA(fast) - EMA(slow)
      Signal Line  = EMA(MACD Line, signal)
      Histogram    = MACD Line - Signal Line
    Bullish: Histogram > 0 and rising | Bearish: Histogram < 0 and falling
    """
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()

    macd_line = (ema_fast - ema_slow).round(6)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean().round(6)
    histogram = (macd_line - signal_line).round(6)

    return pd.DataFrame({
        "macd_line": macd_line,
        "macd_signal": signal_line,
        "macd_hist": histogram,
    })


def add_momentum_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds RSI (14) and MACD (12, 26, 9) columns plus momentum signal classification.
    Momentum Signal:
      OVERBOUGHT   : RSI >= 70
      OVERSOLD     : RSI <= 30
      BULLISH      : MACD Hist > 0 and RSI in (30, 70)
      BEARISH      : MACD Hist < 0 and RSI in (30, 70)
      NEUTRAL      : otherwise
    """
    res = df.copy()
    c = res["close_price"]

    res["rsi_14"] = calc_rsi(c, 14)

    macd_df = calc_macd(c)
    res["macd_line"] = macd_df["macd_line"]
    res["macd_signal"] = macd_df["macd_signal"]
    res["macd_hist"] = macd_df["macd_hist"]

    def _signal(row):
        rsi = row["rsi_14"]
        hist = row["macd_hist"]
        if rsi >= 70:
            return "OVERBOUGHT"
        if rsi <= 30:
            return "OVERSOLD"
        if hist > 0:
            return "BULLISH"
        if hist < 0:
            return "BEARISH"
        return "NEUTRAL"

    res["momentum_signal"] = res.apply(_signal, axis=1)
    return res
