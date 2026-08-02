"""
Volume Indicators: Session VWAP and On-Balance Volume (OBV).

SOURCES & OFFICIAL REFERENCES:
- VWAP: Kissell & Glantz (2003), Optimal Trading Strategies (institutional benchmark)
- OBV: Granville, J. (1963), Granville's New Key to Stock Market Profits
- Investopedia VWAP: https://www.investopedia.com/terms/v/vwap.asp
- Investopedia OBV: https://www.investopedia.com/terms/o/onbalancevolume.asp
- NAGA Indicators Guide: https://naga.com/en/academy/trading-indicators

NOTE: For XAU/USD and EUR/USD on session-based data, VWAP is calculated per
trading day/session. OBV is included as directional flow confirmation only —
treat with caution on FX data where tick volume differs from true volume.
"""

import numpy as np
import pandas as pd


def calc_vwap(df: pd.DataFrame, session_col: str = "price_datetime") -> pd.Series:
    """
    Session VWAP (Volume Weighted Average Price).
    Formula: VWAP = Σ(Typical_Price * Volume) / Σ(Volume)
             Typical_Price = (H + L + C) / 3
    Resets at the start of each trading day.
    """
    res = df.copy()
    res["_typical_price"] = (
        res["high_price"] + res["low_price"] + res["close_price"]
    ) / 3.0

    if session_col in res.columns:
        res["_date"] = pd.to_datetime(res[session_col]).dt.date
    else:
        res["_date"] = res.index.date if hasattr(res.index, "date") else 0

    res["_tp_vol"] = res["_typical_price"] * res.get("volume", pd.Series(1, index=res.index))

    vwap = (
        res.groupby("_date")["_tp_vol"].cumsum()
        / res.groupby("_date")[
            "volume" if "volume" in res.columns else "_tp_vol"
        ].cumsum()
    )

    # Fallback if volume column is missing
    if "volume" not in res.columns:
        vwap = res.groupby("_date")["_typical_price"].expanding().mean().droplevel(0)

    res.drop(columns=["_typical_price", "_tp_vol", "_date"], inplace=True, errors="ignore")
    return vwap.round(5)


def calc_obv(df: pd.DataFrame) -> pd.Series:
    """
    On-Balance Volume (OBV) — Granville (1963).
    Formula:
      OBV_t = OBV_{t-1} + V_t  if C_t > C_{t-1}
      OBV_t = OBV_{t-1} - V_t  if C_t < C_{t-1}
      OBV_t = OBV_{t-1}        if C_t = C_{t-1}
    Rising OBV with rising price = strong bullish confirmation.
    """
    if "volume" not in df.columns:
        return pd.Series(np.nan, index=df.index)

    direction = np.sign(df["close_price"].diff())
    direction.iloc[0] = 0
    return (direction * df["volume"]).cumsum()


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds VWAP, OBV, and Volume Confirmation Signal.
    Confirmation Signal:
      CONFIRM_BUY  : Close > VWAP and OBV rising (OBV > OBV_prev)
      CONFIRM_SELL : Close < VWAP and OBV falling
      NEUTRAL      : otherwise
    """
    res = df.copy()
    res["vwap"] = calc_vwap(res)
    res["obv"] = calc_obv(res)

    res["obv_slope"] = res["obv"].diff()

    def _signal(row):
        try:
            close = row["close_price"]
            vwap = row["vwap"]
            slope = row["obv_slope"]
            if np.isnan(vwap) or np.isnan(slope):
                return "NEUTRAL"
            if close > vwap and slope > 0:
                return "CONFIRM_BUY"
            if close < vwap and slope < 0:
                return "CONFIRM_SELL"
            return "NEUTRAL"
        except Exception:
            return "NEUTRAL"

    res["volume_signal"] = res.apply(_signal, axis=1)
    return res
