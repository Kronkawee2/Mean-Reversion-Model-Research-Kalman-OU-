"""
Trend Indicators: EMA (20, 50, 200), ADX (14), and Trend Bias Classification.

SOURCES & OFFICIAL REFERENCES:
- Wilder, J.W. (1978): New Concepts in Technical Trading Systems (ADX, ATR, RSI originals)
- Investopedia EMA: https://www.investopedia.com/terms/e/ema.asp
- Fidelity Technical Analysis: https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Understanding-Indicators-TA.pdf
"""

import numpy as np
import pandas as pd


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.
    Formula: EMA_t = P_t * k + EMA_{t-1} * (1 - k),  k = 2 / (n + 1)
    """
    return series.ewm(span=period, adjust=False).mean()


def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Wilder's Average Directional Index (ADX) with +DI and -DI.
    Formula:
      TR   = max(H-L, |H-C_prev|, |L-C_prev|)
      +DM  = H - H_prev  if positive and > -(L - L_prev) else 0
      -DM  = L_prev - L  if positive and > (H - H_prev)  else 0
      +DI  = 100 * Smooth(+DM) / Smooth(TR)
      -DI  = 100 * Smooth(-DM) / Smooth(TR)
      DX   = 100 * |+DI - -DI| / (+DI + -DI)
      ADX  = Smooth(DX, period)
    """
    res = df[["high_price", "low_price", "close_price"]].copy()
    h, l, c = res["high_price"], res["low_price"], res["close_price"]
    c_prev = c.shift(1)
    h_prev = h.shift(1)
    l_prev = l.shift(1)

    tr = pd.concat([h - l, (h - c_prev).abs(), (l - c_prev).abs()], axis=1).max(axis=1)

    up_move = h - h_prev
    down_move = l_prev - l

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    plus_dm_s = pd.Series(plus_dm, index=df.index).ewm(span=period, adjust=False).mean()
    minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(span=period, adjust=False).mean()
    tr_s = tr.ewm(span=period, adjust=False).mean()

    plus_di = 100.0 * plus_dm_s / tr_s.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_s / tr_s.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()

    res["adx"] = adx.round(3)
    res["plus_di"] = plus_di.round(3)
    res["minus_di"] = minus_di.round(3)
    return res[["adx", "plus_di", "minus_di"]]


def add_trend_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds EMA (20, 50, 200), ADX (14), and Trend Bias Signal to DataFrame.
    Trend Bias rules:
      STRONG_UPTREND  : Close > EMA20 > EMA50 > EMA200 and ADX > 25
      UPTREND         : Close > EMA20 > EMA50
      STRONG_DOWNTREND: Close < EMA20 < EMA50 < EMA200 and ADX > 25
      DOWNTREND       : Close < EMA20 < EMA50
      SIDEWAYS        : ADX < 20
    """
    res = df.copy()
    c = res["close_price"]

    res["ema_20"] = calc_ema(c, 20)
    res["ema_50"] = calc_ema(c, 50)
    res["ema_200"] = calc_ema(c, 200)

    adx_df = calc_adx(res, period=14)
    res["adx_14"] = adx_df["adx"]
    res["plus_di_14"] = adx_df["plus_di"]
    res["minus_di_14"] = adx_df["minus_di"]

    def _bias(row):
        try:
            cl, e20, e50, e200, adx = (
                row["close_price"], row["ema_20"], row["ema_50"],
                row["ema_200"], row["adx_14"]
            )
            if cl > e20 > e50 > e200 and adx > 25:
                return "STRONG_UPTREND"
            if cl > e20 > e50:
                return "UPTREND"
            if cl < e20 < e50 < e200 and adx > 25:
                return "STRONG_DOWNTREND"
            if cl < e20 < e50:
                return "DOWNTREND"
            return "SIDEWAYS"
        except Exception:
            return "SIDEWAYS"

    res["trend_bias"] = res.apply(_bias, axis=1)
    return res
