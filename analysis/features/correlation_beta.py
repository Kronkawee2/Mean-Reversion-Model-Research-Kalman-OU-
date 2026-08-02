"""
Correlation, Beta, and Spread Feature Engineering Module.

SOURCES & OFFICIAL REFERENCES:
- Engle & Granger (1987): Co-integration and Error Correction: Representation, Estimation, and Testing
- CME Group Precious Metals Intermarket Specifications: https://www.cmegroup.com/
"""

import numpy as np
import pandas as pd


class CorrelationBetaFeatures:
    """Calculates Statistical Arbitrage spread, rolling Beta, and Cointegration Z-Scores."""

    @staticmethod
    def calc_rolling_beta(
        series_asset: pd.Series,
        series_driver: pd.Series,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates rolling OLS Beta coefficient: Beta = Cov(Asset, Driver) / Var(Driver).
        Source: Capital Asset Pricing Model & Cointegration Regression.
        """
        cov = series_asset.rolling(window).cov(series_driver)
        var = series_driver.rolling(window).var().replace(0, np.nan)
        beta = cov / var
        return beta.fillna(1.0)

    @classmethod
    def calc_spread_zscore(
        cls,
        series_asset: pd.Series,
        series_driver: pd.Series,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates stationary cointegrating residual spread Z-score:
        Spread = Price_Asset - Beta * Price_Driver
        Z = (Spread - Mean(Spread)) / Std(Spread)
        Source: Engle-Granger Cointegration & Mean-Reversion Arbitrage.
        """
        beta = cls.calc_rolling_beta(series_asset, series_driver, window=window)
        spread = series_asset - beta * series_driver
        mean_spread = spread.rolling(window).mean()
        std_spread = spread.rolling(window).std().replace(0, np.nan)
        zscore = (spread - mean_spread) / std_spread
        return zscore.fillna(0.0)

    @staticmethod
    def calc_gold_silver_ratio_zscore(
        series_gold: pd.Series,
        series_silver: pd.Series,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates Gold/Silver Ratio Z-score: Z = (Ratio - Mean(Ratio)) / Std(Ratio).
        Source: CME Group Precious Metals Ratio Trading.
        Asset Specific: XAU/USD Only.
        """
        ratio = series_gold / series_silver.replace(0, np.nan)
        mean_r = ratio.rolling(window).mean()
        std_r = ratio.rolling(window).std().replace(0, np.nan)
        zscore = (ratio - mean_r) / std_r
        return zscore.fillna(0.0)

    @staticmethod
    def calc_rolling_correlation(
        series_asset: pd.Series,
        series_driver: pd.Series,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates rolling Pearson correlation coefficient between Asset and Driver.
        Source: Intermarket Analysis Framework.
        """
        corr = series_asset.rolling(window).corr(series_driver)
        return corr.fillna(0.0)
