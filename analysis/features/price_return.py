"""
Price-based and Return-based Feature Engineering Module.

SOURCES & OFFICIAL REFERENCES:
- Campbell, Lo, & MacKinlay (1997): The Econometrics of Financial Markets (Log Returns & Stationarity)
- Investopedia Technical Analysis: https://www.investopedia.com/terms/l/log-return.asp
"""

import numpy as np
import pandas as pd
from typing import Optional


class PriceReturnFeatures:
    """Calculates stationary price and return features."""

    @staticmethod
    def calc_log_return(series: pd.Series, lag: int = 1) -> pd.Series:
        """
        Calculates log return: r_t = ln(P_t / P_{t-lag}).
        Source: Financial Econometrics (Stationary transformation).
        """
        return np.log(series / series.shift(lag)).fillna(0.0)

    @staticmethod
    def calc_price_ema_dist_zscore(
        series: pd.Series,
        ema_period: int = 20,
        std_window: int = 60
    ) -> pd.Series:
        """
        Calculates normalized distance from price to EMA in standard deviations:
        Distance = (Price - EMA_period) / Std_window(Price)
        Source: Mean-Reversion Quant Trading Strategies.
        """
        ema = series.ewm(span=ema_period, adjust=False).mean()
        dist = series - ema
        std = series.rolling(std_window).std().replace(0, np.nan)
        zscore = dist / std
        return zscore.fillna(0.0)

    @staticmethod
    def calc_log_return_slope(
        series: pd.Series,
        window: int = 5
    ) -> pd.Series:
        """
        Calculates rolling OLS slope of log returns over window k.
        Source: Momentum Acceleration Analysis.
        """
        log_ret = np.log(series / series.shift(1)).fillna(0.0)
        
        x = np.arange(window)
        x_mean = x.mean()
        x_var = ((x - x_mean) ** 2).sum()

        def _slope(y_w):
            if np.isnan(y_w).any():
                return np.nan
            y_mean = y_w.mean()
            return ((x - x_mean) * (y_w - y_mean)).sum() / x_var

        return log_ret.rolling(window).apply(_slope, raw=True).fillna(0.0)
