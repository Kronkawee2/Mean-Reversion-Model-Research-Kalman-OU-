"""
Statistical Feature Extraction Module for Volume Profile Distribution.

SOURCES & OFFICIAL REFERENCES:
- Quantitative Statistical Metrics for Price Distribution Skewness & Kurtosis
- GoCharting & Alchemy Markets Volume Profile Analysis: https://alchemymarkets.com/education/indicators/volume-profile/
"""

import numpy as np
import pandas as pd
from typing import Dict


class ProfileStatisticalFeatures:
    """Computes quantitative metrics for Volume Profile distribution shape."""

    @staticmethod
    def extract_statistical_features(profile_data: Dict, min_p: float, max_p: float) -> Dict:
        """
        Extracts quantitative shape features from profile dictionary.

        Returns dict containing:
        - poc_norm: Normalized POC location (0.0 to 1.0)
        - skewness: Volume distribution skewness
        - kurtosis: Volume distribution kurtosis
        - concentration_ratio: POC Volume / Total Volume
        - top_bottom_ratio: Top-half Volume / Bottom-half Volume
        - va_symmetry: (VAH - POC) / (POC - VAL)
        """
        bin_centers = profile_data.get("bin_centers", np.array([]))
        bin_vols = profile_data.get("bin_volumes", np.array([]))
        poc = profile_data.get("poc", np.nan)
        total_vol = profile_data.get("total_volume", 0.0)

        if total_vol == 0 or len(bin_centers) == 0 or max_p == min_p:
            return {
                "poc_norm": 0.5, "skewness": 0.0, "kurtosis": 0.0,
                "concentration_ratio": 0.0, "top_bottom_ratio": 1.0, "va_symmetry": 1.0
            }

        # 1. Normalized POC Location (0.0 to 1.0)
        poc_norm = (poc - min_p) / (max_p - min_p)

        # 2. Weighted Mean and Variance of Volume Distribution
        weights = bin_vols / total_vol
        mean_p = (bin_centers * weights).sum()
        var_p = (weights * (bin_centers - mean_p) ** 2).sum()
        std_p = np.sqrt(var_p) if var_p > 0 else 1e-5

        # 3. Skewness & Kurtosis
        skewness = (weights * ((bin_centers - mean_p) / std_p) ** 3).sum()
        kurtosis = (weights * ((bin_centers - mean_p) / std_p) ** 4).sum() - 3.0

        # 4. Concentration Ratio
        poc_idx = profile_data.get("poc_idx", 0)
        concentration_ratio = bin_vols[poc_idx] / total_vol if total_vol > 0 else 0.0

        # 5. Top vs Bottom Half Volume Ratio
        mid_idx = len(bin_vols) // 2
        top_vol = bin_vols[mid_idx:].sum()
        bot_vol = bin_vols[:mid_idx].sum()
        top_bottom_ratio = (top_vol / bot_vol) if bot_vol > 0 else 1.0

        # 6. Value Area Symmetry
        vah = profile_data.get("vah", poc)
        val = profile_data.get("val", poc)
        upper_span = vah - poc
        lower_span = poc - val
        va_symmetry = (upper_span / lower_span) if lower_span > 0 else 1.0

        return {
            "poc_norm": round(float(poc_norm), 4),
            "skewness": round(float(skewness), 4),
            "kurtosis": round(float(kurtosis), 4),
            "concentration_ratio": round(float(concentration_ratio), 4),
            "top_bottom_ratio": round(float(top_bottom_ratio), 4),
            "va_symmetry": round(float(va_symmetry), 4)
        }
