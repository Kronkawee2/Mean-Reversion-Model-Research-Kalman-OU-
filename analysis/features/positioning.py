"""
CFTC COT Institutional Positioning Feature Engineering Module.

SOURCES & OFFICIAL REFERENCES:
- CFTC Commitment of Traders (COT) Reports: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
- CME Group Institutional Positioning Analysis: https://www.cmegroup.com/
"""

import numpy as np
import pandas as pd


class PositioningFeatures:
    """Transforms raw weekly CFTC COT report data into stationary features."""

    @staticmethod
    def calc_cot_percentile_rank(
        series_comm_net: pd.Series,
        window: int = 52
    ) -> pd.Series:
        """
        Calculates 52-week CFTC Commercial Net Position Min-Max Percentile Rank (0 - 100%):
        Rank = (Net_t - Min_52w) / (Max_52w - Min_52w) * 100
        Source: CFTC Commercial Hedger Extreme Position Analysis.
        """
        min_p = series_comm_net.rolling(window).min()
        max_p = series_comm_net.rolling(window).max()
        range_p = (max_p - min_p).replace(0, np.nan)

        rank = (series_comm_net - min_p) / range_p * 100.0
        return rank.fillna(50.0)

    @staticmethod
    def calc_cot_zscore(
        series_comm_net: pd.Series,
        window: int = 52
    ) -> pd.Series:
        """
        Calculates 52-week CFTC Commercial Net Position Z-Score:
        Z = (Net_t - Mean_52w) / Std_52w
        Source: Institutional Positioning Standardized Factor.
        """
        mean_p = series_comm_net.rolling(window).mean()
        std_p = series_comm_net.rolling(window).std().replace(0, np.nan)
        zscore = (series_comm_net - mean_p) / std_p
        return zscore.fillna(0.0)

    @staticmethod
    def calc_cot_delta_4w(
        series_comm_net: pd.Series,
        lag_weeks: int = 4
    ) -> pd.Series:
        """
        Calculates 4-week CFTC Net Position Change (Flow Momentum):
        Delta_4w = Net_t - Net_{t-4}
        Source: Institutional Capital Accumulation Rate.
        """
        delta = series_comm_net - series_comm_net.shift(lag_weeks)
        return delta.fillna(0.0)
