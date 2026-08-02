"""
SMC Market Structure Engine: Causal Swing High/Low, BOS, CHoCH & Trend Bias.

SOURCES & OFFICIAL REFERENCES:
- Equiti SMC Market Structure Overview: https://www.equiti.com/sc-en/news/trading-ideas/what-is-the-smart-money-concept-smc-in-forex-and-how-can-you-use-it/
- Trade The Pool SMC Terminology: https://tradethepool.com/technical-skill/smart-money-concepts-terminology/
- GitHub smart-money-concepts repository: https://github.com/joshyattridge/smart-money-concepts
"""

import numpy as np
import pandas as pd
from typing import Tuple, List, Optional


class SMCStructureEngine:
    """Detects Causal Swings, Break of Structure (BOS), Change of Character (CHoCH), and Trend Bias."""

    def __init__(self, pivot_window: int = 3):
        self.pivot_window = pivot_window

    def detect_swings(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detects causal Swing Highs and Swing Lows.
        Causal Formula: H_i = max(H_{i-w..i+w}) confirmed at bar i+w (zero look-ahead bias).
        """
        res = df.copy()
        res["swing_high"] = np.nan
        res["swing_low"] = np.nan
        res["is_swing_high"] = False
        res["is_swing_low"] = False

        highs = res["high_price"].values
        lows = res["low_price"].values
        n = len(res)
        w = self.pivot_window

        for i in range(w, n - w):
            if all(highs[i] >= highs[i - j] for j in range(1, w + 1)) and \
               all(highs[i] >= highs[i + j] for j in range(1, w + 1)):
                res.iloc[i + w, res.columns.get_loc("swing_high")] = highs[i]
                res.iloc[i + w, res.columns.get_loc("is_swing_high")] = True

            if all(lows[i] <= lows[i - j] for j in range(1, w + 1)) and \
               all(lows[i] <= lows[i + j] for j in range(1, w + 1)):
                res.iloc[i + w, res.columns.get_loc("swing_low")] = lows[i]
                res.iloc[i + w, res.columns.get_loc("is_swing_low")] = True

        res["swing_high"] = res["swing_high"].ffill()
        res["swing_low"] = res["swing_low"].ffill()
        return res

    def detect_bos_choch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detects Break of Structure (BOS) and Change of Character (CHoCH).
        - Bullish BOS: Close > Previous Swing High in Uptrend.
        - Bearish BOS: Close < Previous Swing Low in Downtrend.
        - Bullish CHoCH: Close > Previous Swing High in Downtrend (Reversal).
        - Bearish CHoCH: Close < Previous Swing Low in Uptrend (Reversal).
        """
        res = self.detect_swings(df)
        res["smc_structure_signal"] = None
        res["smc_trend_bias"] = "NEUTRAL"

        closes = res["close_price"].values
        swing_h = res["swing_high"].values
        swing_l = res["swing_low"].values

        current_trend = "NEUTRAL"

        for i in range(1, len(res)):
            c_curr = closes[i]
            sh_prev = swing_h[i - 1]
            sl_prev = swing_l[i - 1]

            if pd.isna(sh_prev) or pd.isna(sl_prev):
                continue

            # Bullish Break
            if c_curr > sh_prev:
                if current_trend == "BEARISH":
                    res.iloc[i, res.columns.get_loc("smc_structure_signal")] = "BULLISH_CHOCH"
                    current_trend = "BULLISH"
                elif current_trend == "BULLISH":
                    res.iloc[i, res.columns.get_loc("smc_structure_signal")] = "BULLISH_BOS"
                else:
                    current_trend = "BULLISH"

            # Bearish Break
            elif c_curr < sl_prev:
                if current_trend == "BULLISH":
                    res.iloc[i, res.columns.get_loc("smc_structure_signal")] = "BEARISH_CHOCH"
                    current_trend = "BEARISH"
                elif current_trend == "BEARISH":
                    res.iloc[i, res.columns.get_loc("smc_structure_signal")] = "BEARISH_BOS"
                else:
                    current_trend = "BEARISH"

            res.iloc[i, res.columns.get_loc("smc_trend_bias")] = current_trend

        return res
