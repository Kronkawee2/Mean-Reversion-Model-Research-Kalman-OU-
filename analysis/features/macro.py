"""
Macro-based Feature Engineering Module.

SOURCES & OFFICIAL REFERENCES:
- ICE US Dollar Index (DXY) Specifications: https://www.theice.com/dollar-index
- CBOE Volatility Index (VIX) Market Data: https://www.cboe.com/tradable_products/vix/
- CME Group Treasury Yield & Real Yield Analytics: https://www.cmegroup.com/
"""

import numpy as np
import pandas as pd


class MacroFeatures:
    """Calculates macroeconomic and inter-market features for Gold and EUR/USD."""

    @staticmethod
    def calc_dxy_return_zscore(
        series_dxy: pd.Series,
        lag: int = 1,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates stationary DXY return momentum Z-score:
        r_DXY = ln(DXY_t / DXY_{t-lag})
        Z = (r_DXY - Mean(r_DXY)) / Std(r_DXY)
        Source: ICE US Dollar Index Impulse Analysis.
        """
        log_ret = np.log(series_dxy / series_dxy.shift(lag)).fillna(0.0)
        mean_ret = log_ret.rolling(window).mean()
        std_ret = log_ret.rolling(window).std().replace(0, np.nan)
        zscore = (log_ret - mean_ret) / std_ret
        return zscore.fillna(0.0)

    @staticmethod
    def calc_real_yield_proxy(
        series_us10y: pd.Series,
        series_dxy: pd.Series,
        lag: int = 1
    ) -> pd.Series:
        """
        Calculates Real Yield Proxy Return Delta: r_US10Y - r_DXY.
        Source: Federal Reserve Real Rate Macro Framework.
        """
        ret_us10y = np.log(series_us10y / series_us10y.shift(lag)).fillna(0.0)
        ret_dxy = np.log(series_dxy / series_dxy.shift(lag)).fillna(0.0)
        real_yield_proxy = ret_us10y - ret_dxy
        return real_yield_proxy.fillna(0.0)

    @staticmethod
    def calc_gdx_gold_residual(
        series_gold: pd.Series,
        series_gdx: pd.Series,
        window: int = 60
    ) -> pd.Series:
        """
        Calculates Gold Spot Return vs GDX Mining Stock Return Residual:
        Residual = r_Gold - Beta * r_GDX
        Source: VanEck Gold Miners Mining Lead Indicator.
        Asset Specific: XAU/USD Only.
        """
        ret_gold = np.log(series_gold / series_gold.shift(1)).fillna(0.0)
        ret_gdx = np.log(series_gdx / series_gdx.shift(1)).fillna(0.0)

        cov = ret_gold.rolling(window).cov(ret_gdx)
        var = ret_gdx.rolling(window).var().replace(0, np.nan)
        beta = (cov / var).fillna(1.0)

        residual = ret_gold - beta * ret_gdx
        return residual.fillna(0.0)

    @staticmethod
    def calc_vix_regime_flag(
        series_vix: pd.Series,
        threshold: float = 25.0
    ) -> pd.Series:
        """
        Calculates binary VIX Volatility Crisis Regime Flag:
        1.0 if VIX > threshold (Crisis Regime), else 0.0 (Normal Regime).
        Source: CBOE Volatility Index Guidelines.
        """
        flag = (series_vix > threshold).astype(float)
        return flag.fillna(0.0)
