"""
Volume Profile Trading Signals & Rule-Based Strategy Engine.

SOURCES & OFFICIAL REFERENCES:
- NinjaTrader Volume Profile Trading Rules: https://ninjatrader.com/futures/blogs/trade-futures-understanding-the-4-common-volume-profile-shapes/
- Alchemy Markets Volume Profile Effective Trading Guide: https://alchemymarkets.com/education/indicators/volume-profile/
"""

import numpy as np
import pandas as pd
from typing import Dict


class ProfileSignalEngine:
    """Generates quantitative trading signals based on profile shape and price position relative to POC/VA."""

    @staticmethod
    def generate_shape_signals(current_price: float, profile_data: Dict, shape_label: str) -> Dict:
        """
        Evaluates current price position against profile structure (POC, VAH, VAL) and shape.

        Returns dict:
        - action: 'BUY', 'SELL', 'HOLD'
        - bias: 'BULLISH', 'BEARISH', 'NEUTRAL'
        - target_price: Take profit target
        - stop_loss: Recommended stop loss
        - reason: Explanation string
        """
        poc = profile_data.get("poc", current_price)
        vah = profile_data.get("vah", current_price)
        val = profile_data.get("val", current_price)

        if np.isnan(poc) or np.isnan(vah) or np.isnan(val):
            return {"action": "HOLD", "bias": "NEUTRAL", "target_price": np.nan, "stop_loss": np.nan, "reason": "No profile data"}

        # 1. P-shape (Bullish Continuation / Short Covering)
        if shape_label == "P_SHAPE":
            if current_price >= poc:
                sl = val
                tp = current_price + 2.0 * (current_price - sl)
                return {
                    "action": "BUY",
                    "bias": "BULLISH",
                    "target_price": round(tp, 4),
                    "stop_loss": round(sl, 4),
                    "reason": "P-shape Bullish Continuation above POC"
                }
            else:
                return {"action": "HOLD", "bias": "BULLISH", "target_price": np.nan, "stop_loss": np.nan, "reason": "P-shape pullback below POC"}

        # 2. b-shape (Bearish Continuation / Long Liquidation)
        elif shape_label == "B_SHAPE":
            if current_price <= poc:
                sl = vah
                tp = current_price - 2.0 * (sl - current_price)
                return {
                    "action": "SELL",
                    "bias": "BEARISH",
                    "target_price": round(tp, 4),
                    "stop_loss": round(sl, 4),
                    "reason": "b-shape Bearish Continuation below POC"
                }
            else:
                return {"action": "HOLD", "bias": "BEARISH", "target_price": np.nan, "stop_loss": np.nan, "reason": "b-shape retracement above POC"}

        # 3. D-shape (Balanced Mean-Reversion)
        elif shape_label == "D_SHAPE":
            if current_price <= val:
                sl = val - (poc - val) * 0.5
                return {
                    "action": "BUY",
                    "bias": "NEUTRAL_RANGE",
                    "target_price": round(poc, 4),
                    "stop_loss": round(sl, 4),
                    "reason": "D-shape Mean-Reversion Buy at VAL"
                }
            elif current_price >= vah:
                sl = vah + (vah - poc) * 0.5
                return {
                    "action": "SELL",
                    "bias": "NEUTRAL_RANGE",
                    "target_price": round(poc, 4),
                    "stop_loss": round(sl, 4),
                    "reason": "D-shape Mean-Reversion Sell at VAH"
                }

        return {"action": "HOLD", "bias": "NEUTRAL", "target_price": np.nan, "stop_loss": np.nan, "reason": "Price inside D-shape Value Area"}
