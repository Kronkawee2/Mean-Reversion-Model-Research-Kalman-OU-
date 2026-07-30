"""
Feature Engineering Module for Quantitative Divergence System.

SOURCES & MATHEMATICAL FORMULAS:
- Rolling Z-Score & Cointegration Residual Spread: Standard Statistical Arbitrage (Engle-Granger Framework)
- Linear Regression Slope: Ordinary Least Squares (OLS) Polynomial Slope
- CFTC COT Commercial Index: 52-Week Normalized Institutional Position Index (Standard Quant Futures Formula)

REFERENCES:
- Investopedia Technical Analysis: https://www.investopedia.com/terms/d/divergence.asp
- Corporate Finance Institute (CFI): https://corporatefinanceinstitute.com/resources/career-map/sell-side/capital-markets/divergence/
"""

import numpy as np
import pandas as pd
from typing import Tuple, Optional


class DivergenceFeatureEngine:
    """Computes mathematical feature transformations for divergence detection."""

    @staticmethod
    def calc_rolling_beta(
        series_asset: pd.Series,
        series_driver: pd.Series,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates rolling OLS Beta coefficient:
        Formula: Beta = Cov(Asset, Driver) / Var(Driver)
        Source: Portfolio Management & Financial Risk Theory (CFI)
        """
        cov = series_asset.rolling(window).cov(series_driver)
        var = series_driver.rolling(window).var()
        beta = cov / var.replace(0, np.nan)
        return beta.fillna(1.0)

    @classmethod
    def calc_beta_spread_zscore(
        cls,
        series_asset: pd.Series,
        series_driver: pd.Series,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates cointegrating residual spread Z-score:
        Formula:
          Spread = Price_Asset - Beta * Price_Driver
          Z-Score = (Spread - Mean(Spread_N)) / Std(Spread_N)
        Source: Engle-Granger Cointegration & Statistical Arbitrage
        """
        beta = cls.calc_rolling_beta(series_asset, series_driver, window=window)
        spread = series_asset - beta * series_driver

        mean_spread = spread.rolling(window).mean()
        std_spread = spread.rolling(window).std().replace(0, np.nan)

        zscore = (spread - mean_spread) / std_spread
        return zscore.fillna(0.0)

    @staticmethod
    def calc_ratio_zscore(
        series_a: pd.Series,
        series_b: pd.Series,
        window: int = 30
    ) -> pd.Series:
        """
        Calculates rolling Z-score of asset price ratio (e.g. Gold / Silver Ratio or Gold / DXY Ratio):
        Formula:
          Ratio = Series_A / Series_B
          Z-Score = (Ratio - Mean(Ratio_N)) / Std(Ratio_N)
        Source: Inter-market Relative Value Analysis
        """
        ratio = series_a / series_b.replace(0, np.nan)
        mean_ratio = ratio.rolling(window).mean()
        std_ratio = ratio.rolling(window).std().replace(0, np.nan)

        zscore = (ratio - mean_ratio) / std_ratio
        return zscore.fillna(0.0)

    @staticmethod
    def calc_rolling_slope(
        series: pd.Series,
        window: int = 5
    ) -> pd.Series:
        """
        Calculates rolling linear regression slope over window k using OLS.
        Formula: Slope = Cov(x, y) / Var(x) where x = [0, 1, ..., k-1].
        Source: Quantitative Trend Analysis & Momentum Slope
        """
        if len(series) < window:
            return pd.Series(index=series.index, data=np.nan)

        x = np.arange(window)
        x_mean = x.mean()
        x_var = ((x - x_mean) ** 2).sum()

        def _slope(y_window):
            if np.isnan(y_window).any():
                return np.nan
            y_mean = y_window.mean()
            cov = ((x - x_mean) * (y_window - y_mean)).sum()
            return cov / x_var

        return series.rolling(window).apply(_slope, raw=True).fillna(0.0)

    @staticmethod
    def calc_cot_index(
        net_commercial_position: pd.Series,
        window: int = 52
    ) -> pd.Series:
        """
        Calculates 52-week CFTC COT Commercial Index (% Index):
        Formula: COT Index = (Net_Comm - Min_52w) / (Max_52w - Min_52w) * 100
        Source: CFTC Commitment of Traders Quantitative Analysis
        URL: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
        """
        min_pos = net_commercial_position.rolling(window).min()
        max_pos = net_commercial_position.rolling(window).max()
        range_pos = (max_pos - min_pos).replace(0, np.nan)

        cot_index = (net_commercial_position - min_pos) / range_pos * 100.0
        return cot_index.fillna(50.0)
