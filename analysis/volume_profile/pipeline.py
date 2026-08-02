"""
Master Volume Profile Pipeline Engine.
Executes Volume-at-Price Histogram, Statistical Feature Extraction, Shape Classification, and Signal Generation.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional

from .calculator import VolumeProfileCalculator
from .statistical_features import ProfileStatisticalFeatures
from .classifier import ProfileClassifier
from .signals import ProfileSignalEngine


class VolumeProfilePipeline:
    """Master Volume Profile Transformer & Classifier Pipeline for XAU/USD and EUR/USD."""

    def __init__(self, num_bins: int = 50, value_area_pct: float = 0.70):
        self.calc = VolumeProfileCalculator(num_bins=num_bins, value_area_pct=value_area_pct)
        self.stats_extractor = ProfileStatisticalFeatures()
        self.classifier = ProfileClassifier()
        self.signal_engine = ProfileSignalEngine()

    def process(self, df: pd.DataFrame) -> Dict:
        """
        Processes OHLCV DataFrame and outputs Volume Profile structure, stats, shape, and signal.
        """
        if df.empty or len(df) < 2:
            return {"shape_label": "UNCLASSIFIED", "action": "HOLD", "poc": np.nan, "vah": np.nan, "val": np.nan}

        min_p = float(df["close_price"].min())
        max_p = float(df["close_price"].max())

        profile = self.calc.compute_profile(df)
        stats = self.stats_extractor.extract_statistical_features(profile, min_p, max_p)
        shape_label = self.classifier.classify_profile(stats)

        current_price = float(df["close_price"].iloc[-1])
        trade_signal = self.signal_engine.generate_shape_signals(current_price, profile, shape_label)

        return {
            "profile_data": profile,
            "stats": stats,
            "shape_label": shape_label,
            "poc": profile.get("poc", np.nan),
            "vah": profile.get("vah", np.nan),
            "val": profile.get("val", np.nan),
            "action": trade_signal.get("action", "HOLD"),
            "bias": trade_signal.get("bias", "NEUTRAL"),
            "target_price": trade_signal.get("target_price", np.nan),
            "stop_loss": trade_signal.get("stop_loss", np.nan),
            "reason": trade_signal.get("reason", "")
        }

    def transform_df(self, df: pd.DataFrame, window: int = 50) -> pd.DataFrame:
        """
        Rolling window transformation attaching Volume Profile features to DataFrame.
        """
        res = df.copy()
        res["vp_poc"] = np.nan
        res["vp_vah"] = np.nan
        res["vp_val"] = np.nan
        res["vp_shape"] = "UNCLASSIFIED"
        res["vp_action"] = "HOLD"

        n = len(res)
        for i in range(window, n):
            sub_df = res.iloc[i - window:i]
            out = self.process(sub_df)

            res.iloc[i, res.columns.get_loc("vp_poc")] = out["poc"]
            res.iloc[i, res.columns.get_loc("vp_vah")] = out["vah"]
            res.iloc[i, res.columns.get_loc("vp_val")] = out["val"]
            res.iloc[i, res.columns.get_loc("vp_shape")] = out["shape_label"]
            res.iloc[i, res.columns.get_loc("vp_action")] = out["action"]

        return res
