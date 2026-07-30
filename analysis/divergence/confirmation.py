"""
Confirmation & Regime Filtering Module.

SOURCES & OFFICIAL REFERENCES:
- CBOE Volatility Index (VIX) Regime Guidelines: https://www.cboe.com/tradable_products/vix/
- Rolling Correlation Breakdown & Intermarket Risk Management Principles (CFI & CME Group)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


class DivergenceConfirmationFilter:
    """
    Applies Volatility Regime (VIX/ATR) filters, Inter-Market Rolling Correlation Stability checks,
    and Multi-Timeframe (MTF) trend bias alignment.
    """

    @staticmethod
    def filter_volatility_regime(
        df: pd.DataFrame,
        vix_col: str = "vix_close",
        vix_threshold: float = 25.0
    ) -> pd.Series:
        """
        Determines volatility regime based on VIX (^VIX).
        Source: CBOE Volatility Index Guidelines
        - True: Stable / Normal regime (VIX <= 25.0)
        - False: High crisis regime (VIX > 25.0) -> Position sizing scaled down 50%
        """
        if vix_col not in df.columns:
            return pd.Series(index=df.index, data=True)

        is_stable = df[vix_col].fillna(0.0) <= vix_threshold
        return is_stable

    @staticmethod
    def check_correlation_stability(
        series_asset: pd.Series,
        series_driver: pd.Series,
        window: int = 60,
        expected_negative: bool = True,
        corr_threshold: float = -0.30
    ) -> pd.Series:
        """
        Checks rolling correlation stability.
        Source: Cointegration & Rolling Pearson Correlation Theory
        For inverse assets (e.g. Gold & DXY), correlation must be sufficiently negative (< -0.30).
        If correlation breaks down towards positive, inter-market driver signals are muted.
        """
        corr = series_asset.rolling(window).corr(series_driver)

        if expected_negative:
            is_valid = corr <= corr_threshold
        else:
            is_valid = corr >= abs(corr_threshold)

        return is_valid.fillna(False)

    @staticmethod
    def align_htf_trend(
        df_ltf: pd.DataFrame,
        df_htf: pd.DataFrame,
        htf_ema_col: str = "ema_50",
        time_col: str = "price_datetime"
    ) -> pd.DataFrame:
        """
        Aligns Higher Timeframe (HTF 1d/4h) trend bias with Lower Timeframe (LTF 15m/5m) dataset.
        Source: Multi-Timeframe Alignment Principles (Investopedia / LiteFinance)
        Bullish HTF Bias: HTF Price > HTF EMA50.
        """
        res = df_ltf.copy()
        if df_htf.empty or htf_ema_col not in df_htf.columns:
            res["htf_bias"] = "NEUTRAL"
            return res

        htf_clean = df_htf.sort_values(time_col).copy()
        htf_clean["htf_bias"] = np.where(
            htf_clean["close_price"] > htf_clean[htf_ema_col],
            "BULLISH",
            "BEARISH"
        )

        merged = pd.merge_asof(
            res.sort_values(time_col),
            htf_clean[[time_col, "htf_bias"]],
            on=time_col,
            direction="backward"
        )
        return merged
