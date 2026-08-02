"""
Technical Analysis Master Pipeline for XAU/USD and EUR/USD.
Runs all modules (Trend, Momentum, Volatility, Volume, Support/Resistance)
in a single call and returns one unified DataFrame.
"""

import numpy as np
import pandas as pd

from .trend import add_trend_features
from .momentum import add_momentum_features
from .volatility import add_volatility_features
from .volume import add_volume_features
from .support_resistance import add_sr_features


class TechnicalAnalysisEngine:
    """
    Unified Technical Analysis Engine for XAU/USD and EUR/USD.
    Applies: Trend (EMA, ADX), Momentum (RSI, MACD), Volatility (ATR, BB),
             Volume (VWAP, OBV), Support/Resistance (Fibonacci, S/R Zones).
    """

    def __init__(self, sr_lookback: int = 50):
        self.sr_lookback = sr_lookback

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Applies all technical indicators and signals in sequence.
        Input columns required: open_price, high_price, low_price, close_price
        Optional: volume, price_datetime
        Returns enriched DataFrame with all indicator columns attached.
        """
        if df.empty or len(df) < 20:
            return df

        res = df.copy()
        res = add_trend_features(res)
        res = add_momentum_features(res)
        res = add_volatility_features(res)
        res = add_volume_features(res)
        res = add_sr_features(res, lookback_window=self.sr_lookback)
        return res

    def get_signal_summary(self, df: pd.DataFrame) -> dict:
        """
        Returns a consolidated signal summary from the last row.
        """
        if df.empty:
            return {}

        row = df.iloc[-1]
        return {
            "trend_bias": row.get("trend_bias", "SIDEWAYS"),
            "momentum_signal": row.get("momentum_signal", "NEUTRAL"),
            "vol_regime": row.get("vol_regime", "NORMAL"),
            "volume_signal": row.get("volume_signal", "NEUTRAL"),
            "rsi_14": row.get("rsi_14", np.nan),
            "adx_14": row.get("adx_14", np.nan),
            "atr_14": row.get("atr_14", np.nan),
            "bb_pct_b": row.get("bb_pct_b", np.nan),
            "macd_hist": row.get("macd_hist", np.nan),
            "near_fib_level": row.get("near_fib_level", False),
        }
