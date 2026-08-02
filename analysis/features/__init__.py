"""
Quantitative Feature Engineering Package for XAU/USD & EUR/USD.
Provides ML-ready features: log returns, Garman-Klass volatility, rolling beta,
cointegration spread, macro z-scores, and CFTC COT positioning metrics.

NOTE: Low-level indicator functions (EMA, RSI, ATR) are provided as convenience
aliases but computed via analysis.technical_analysis to avoid duplication.
"""

import numpy as np
import pandas as pd

from .price_return import PriceReturnFeatures
from .volatility import VolatilityFeatures
from .correlation_beta import CorrelationBetaFeatures
from .macro import MacroFeatures
from .positioning import PositioningFeatures
from .pipeline import QuantFeaturePipeline

# Delegate indicator functions to technical_analysis to avoid duplication
from analysis.technical_analysis.trend import calc_ema
from analysis.technical_analysis.momentum import calc_rsi
from analysis.technical_analysis.volatility import calc_atr


def generate_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate core ML-ready features from OHLCV DataFrame.
    Expects columns: open_price, high_price, low_price, close_price, volume
    """
    if df.empty or len(df) < 5:
        return df

    res = df.copy()
    c = res["close_price"]

    res["log_return"] = PriceReturnFeatures.calc_log_return(c)
    res["pct_change"] = c.pct_change()

    res["ema_20"] = calc_ema(c, 20)
    res["ema_50"] = calc_ema(c, 50)
    res["ema_200"] = calc_ema(c, 200)

    res["rsi_14"] = calc_rsi(c, 14)
    res["atr_14"] = calc_atr(res, 14)
    res["volatility_20"] = res["log_return"].rolling(20).std()

    res["dist_ema_20"] = (c - res["ema_20"]) / res["ema_20"]
    res["dist_ema_50"] = (c - res["ema_50"]) / res["ema_50"]
    res["dist_ema_200"] = (c - res["ema_200"]) / res["ema_200"]

    res["garman_klass_vol"] = VolatilityFeatures.calc_garman_klass_vol(res)
    return res


__all__ = [
    "calc_ema",
    "calc_rsi",
    "calc_atr",
    "generate_features",
    "PriceReturnFeatures",
    "VolatilityFeatures",
    "CorrelationBetaFeatures",
    "MacroFeatures",
    "PositioningFeatures",
    "QuantFeaturePipeline",
]
