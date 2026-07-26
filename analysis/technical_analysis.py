"""
Trend Analysis Module focused on Exponential Moving Averages (EMA 20, EMA 50, EMA 100).
Designed to serve as a clean trend filter for custom Quant Models.
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Calculates EMA 20, EMA 50, and EMA 100 for Trend Identification."""

    def __init__(self):
        logger.info("Trend Analyzer initialized (EMA 20, 50, 100)")

    def calculate_ema(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate Exponential Moving Average for a given period."""
        return prices.ewm(span=period, adjust=False).mean()

    def add_ema_indicators(self, df: pd.DataFrame,
                           calc_ema20: bool = True,
                           calc_ema50: bool = True,
                           calc_ema100: bool = True) -> pd.DataFrame:
        """
        Add EMA 20, EMA 50, and EMA 100 columns to a price DataFrame.
        Each EMA can be toggled on/off.
        """
        if df.empty or 'Close' not in df.columns:
            return df

        df_out = df.copy()
        close = df_out['Close']

        if calc_ema20:
            df_out['EMA_20'] = self.calculate_ema(close, 20)
        if calc_ema50:
            df_out['EMA_50'] = self.calculate_ema(close, 50)
        if calc_ema100:
            df_out['EMA_100'] = self.calculate_ema(close, 100)

        return df_out

    def get_trend_summary(self, df: pd.DataFrame) -> Dict:
        """
        Analyze current trend direction based on EMA 20, 50, and 100 alignments.
        Returns trend direction (UPTREND, DOWNTREND, SIDEWAYS) and EMA values.
        """
        if df.empty or len(df) < 2:
            return {
                'trend': 'UNKNOWN',
                'close': 0.0,
                'ema20': None,
                'ema50': None,
                'ema100': None
            }

        df_ema = self.add_ema_indicators(df, calc_ema20=True, calc_ema50=True, calc_ema100=True)
        close = float(df_ema['Close'].iloc[-1])
        ema20 = float(df_ema['EMA_20'].iloc[-1])
        ema50 = float(df_ema['EMA_50'].iloc[-1])
        ema100 = float(df_ema['EMA_100'].iloc[-1])

        # Trend Determination:
        # UPTREND: Price > EMA 20 > EMA 50 > EMA 100
        # DOWNTREND: Price < EMA 20 < EMA 50 < EMA 100
        # Otherwise: SIDEWAYS / MIXED
        if close > ema20 > ema50 > ema100:
            trend = 'STRONG_UPTREND'
        elif close > ema20 and ema20 > ema50:
            trend = 'UPTREND'
        elif close < ema20 < ema50 < ema100:
            trend = 'STRONG_DOWNTREND'
        elif close < ema20 and ema20 < ema50:
            trend = 'DOWNTREND'
        else:
            trend = 'SIDEWAYS'

        return {
            'trend': trend,
            'close': round(close, 5),
            'ema20': round(ema20, 5),
            'ema50': round(ema50, 5),
            'ema100': round(ema100, 5),
        }


# Legacy alias for backward compatibility
TechnicalAnalyzer = TrendAnalyzer


if __name__ == "__main__":
    import numpy as np

    # Test with dummy data
    dates = pd.date_range('2026-01-01', periods=120)
    prices = 2000 + np.cumsum(np.random.randn(120) * 5)
    df = pd.DataFrame({'Close': prices}, index=dates)

    analyzer = TrendAnalyzer()
    df_result = analyzer.add_ema_indicators(df, calc_ema20=True, calc_ema50=True, calc_ema100=True)
    summary = analyzer.get_trend_summary(df)

    print("Trend Summary Test:")
    print(summary)
    print("\nLatest 5 rows with EMA:")
    print(df_result[['Close', 'EMA_20', 'EMA_50', 'EMA_100']].tail(5))
