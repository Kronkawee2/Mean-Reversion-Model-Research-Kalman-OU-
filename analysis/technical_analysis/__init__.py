"""
Quantitative Technical Analysis Package for XAU/USD & EUR/USD.
Modular: Trend (EMA, ADX), Momentum (RSI, MACD), Volatility (ATR, BB),
         Volume (VWAP, OBV), Support/Resistance (Fibonacci, S/R Zones).
"""

from .trend import calc_ema, calc_adx, add_trend_features
from .momentum import calc_rsi, calc_macd, add_momentum_features
from .volatility import calc_atr, calc_bollinger, add_volatility_features
from .volume import calc_vwap, calc_obv, add_volume_features
from .support_resistance import calc_fibonacci_levels, detect_sr_zones, add_sr_features
from .pipeline import TechnicalAnalysisEngine

# Legacy aliases for backward compatibility
TrendAnalyzer = TechnicalAnalysisEngine
TechnicalAnalyzer = TechnicalAnalysisEngine

__all__ = [
    "TechnicalAnalysisEngine",
    "TrendAnalyzer",
    "TechnicalAnalyzer",
    # Trend
    "calc_ema",
    "calc_adx",
    "add_trend_features",
    # Momentum
    "calc_rsi",
    "calc_macd",
    "add_momentum_features",
    # Volatility
    "calc_atr",
    "calc_bollinger",
    "add_volatility_features",
    # Volume
    "calc_vwap",
    "calc_obv",
    "add_volume_features",
    # S/R
    "calc_fibonacci_levels",
    "detect_sr_zones",
    "add_sr_features",
]
