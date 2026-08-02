"""
Profile Shape Classifier Engine: P-shape, b-shape, D-shape Classification.

SOURCES & OFFICIAL REFERENCES:
- NinjaTrader Volume Profile Shapes (D, P, b, B): https://ninjatrader.com/futures/blogs/trade-futures-understanding-the-4-common-volume-profile-shapes/
- Trader-Dale Volume Profile Shape Interpretation: https://www.trader-dale.com/how-to-read-volume-profile-shapes-what-the-market-is-really-telling-you/
"""

from typing import Dict


class ProfileClassifier:
    """Classifies Volume Profile distributions into P-shape, b-shape, or D-shape."""

    @staticmethod
    def detect_p_shape(stats: Dict) -> bool:
        """
        Detects P-shape (Bullish Short Covering / Upward Expansion).
        Condition: POC in upper range (>= 0.65) and Top-to-Bottom Volume Ratio >= 1.5.
        """
        poc_norm = stats.get("poc_norm", 0.5)
        top_bot_ratio = stats.get("top_bottom_ratio", 1.0)
        return (poc_norm >= 0.65) and (top_bot_ratio >= 1.4)

    @staticmethod
    def detect_b_shape(stats: Dict) -> bool:
        """
        Detects b-shape (Bearish Long Liquidation / Downward Expansion).
        Condition: POC in lower range (<= 0.35) and Top-to-Bottom Volume Ratio <= 0.67.
        """
        poc_norm = stats.get("poc_norm", 0.5)
        top_bot_ratio = stats.get("top_bottom_ratio", 1.0)
        return (poc_norm <= 0.35) and (top_bot_ratio <= 0.70)

    @staticmethod
    def detect_d_shape(stats: Dict) -> bool:
        """
        Detects D-shape (Balanced Market / Fair Value Equilibrium).
        Condition: POC in middle of range (0.40 <= POC_norm <= 0.60) and |Skewness| <= 0.5.
        """
        poc_norm = stats.get("poc_norm", 0.5)
        skewness = abs(stats.get("skewness", 0.0))
        return (0.40 <= poc_norm <= 0.60) and (skewness <= 0.6)

    @classmethod
    def classify_profile(cls, stats: Dict) -> str:
        """
        Main classifier returning primary shape label:
        'P_SHAPE', 'B_SHAPE', 'D_SHAPE', or 'BALANCED'
        """
        if cls.detect_p_shape(stats):
            return "P_SHAPE"
        elif cls.detect_b_shape(stats):
            return "B_SHAPE"
        elif cls.detect_d_shape(stats):
            return "D_SHAPE"
        else:
            # Fallback classification based on POC Location
            poc_norm = stats.get("poc_norm", 0.5)
            if poc_norm >= 0.60:
                return "P_SHAPE"
            elif poc_norm <= 0.40:
                return "B_SHAPE"
            else:
                return "D_SHAPE"
