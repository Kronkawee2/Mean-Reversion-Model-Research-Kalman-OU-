"""
Volatility Feature Engineering Module.

SOURCES & OFFICIAL REFERENCES:
- Garman & Klass (1980): On the Estimation of Security Price Volatility from High-Low Prices
- Parkinson (1980): The Extreme Value Method for Estimating the Variance of the Rate of Return
- CBOE Volatility Index Guidelines: https://www.cboe.com/tradable_products/vix/
"""

import numpy as np
import pandas as pd


class VolatilityFeatures:
    """Calculates advanced volatility estimators (OHLC & Realized Volatility Ratios)."""

    @staticmethod
    def calc_garman_klass_vol(df: pd.DataFrame, window: int = 20) -> pd.Series:
        """
        Calculates Garman-Klass volatility using Open, High, Low, Close.
        8x more efficient than standard close-to-close volatility.
        Source: Garman & Klass (1980) Journal of Business.
        """
        log_hl = np.log(df["high_price"] / df["low_price"])
        log_co = np.log(df["close_price"] / df["open_price"])

        variance = 0.5 * (log_hl ** 2) - (2 * np.log(2) - 1) * (log_co ** 2)
        rolling_var = variance.rolling(window).mean()
        gk_vol = np.sqrt(np.maximum(rolling_var, 0.0))
        return gk_vol.fillna(0.0)

    @staticmethod
    def calc_parkinson_vol(df: pd.DataFrame, window: int = 20) -> pd.Series:
        """
        Calculates Parkinson volatility using High and Low prices.
        5x more efficient than close-to-close volatility.
        Source: Parkinson (1980) Journal of Business.
        """
        log_hl = np.log(df["high_price"] / df["low_price"])
        variance = (log_hl ** 2) / (4 * np.log(2))
        rolling_var = variance.rolling(window).mean()
        p_vol = np.sqrt(np.maximum(rolling_var, 0.0))
        return p_vol.fillna(0.0)

    @staticmethod
    def calc_normalized_atr_pct(df: pd.DataFrame, window: int = 14) -> pd.Series:
        """
        Calculates normalized ATR as % of current price: (ATR_N / Close) * 100.
        Source: J. Welles Wilder ATR Normalization.
        """
        high = df["high_price"]
        low = df["low_price"]
        close = df["close_price"]

        tr = np.maximum(
            high - low,
            np.maximum(
                abs(high - close.shift(1)),
                abs(low - close.shift(1))
            )
        )
        atr = tr.rolling(window).mean()
        atr_pct = (atr / close) * 100.0
        return atr_pct.fillna(0.0)

    @staticmethod
    def calc_volatility_ratio(
        series_returns: pd.Series,
        short_window: int = 10,
        long_window: int = 60
    ) -> pd.Series:
        """
        Calculates Realized Volatility Ratio: Std(r_short) / Std(r_long).
        Detects volatility compression (< 0.7) and expansion (> 1.3).
        """
        vol_short = series_returns.rolling(short_window).std()
        vol_long = series_returns.rolling(long_window).std().replace(0, np.nan)
        ratio = vol_short / vol_long
        return ratio.fillna(1.0)
