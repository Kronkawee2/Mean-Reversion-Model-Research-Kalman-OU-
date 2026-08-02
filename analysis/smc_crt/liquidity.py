"""
SMC Liquidity Engine: Equal Highs/Lows, Liquidity Sweeps, and Stop Hunts.

SOURCES & OFFICIAL REFERENCES:
- DYOR Academy SMC Price Action: https://dyor.net/academy/en/price_action/smart-money-concepts
- ACY Securities Confirmation Model: https://acy.com/en/market-news/education/confirmation-model-ob-fvg-liquidity-sweep-j-o-20251112-094218/
"""

import numpy as np
import pandas as pd


class SMCLiquidityEngine:
    """Detects Equal Highs/Lows (EQH/EQL), Liquidity Sweeps (BSL/SSL), and Stop Hunts."""

    def __init__(self, eq_tolerance_pct: float = 0.0005):
        self.eq_tolerance_pct = eq_tolerance_pct

    def detect_equal_highs_lows(self, df: pd.DataFrame, window: int = 50) -> pd.DataFrame:
        """
        Detects Equal Highs (EQH) and Equal Lows (EQL) liquidity pools within window N.
        Formula: |P1 - P2| / P <= 0.0005 (0.05% tolerance).
        """
        res = df.copy()
        res["is_eqh"] = False
        res["is_eql"] = False

        highs = res["high_price"].values
        lows = res["low_price"].values
        n = len(res)

        for i in range(1, n):
            # Check previous highs within window
            for j in range(1, min(i, window)):
                if abs(highs[i] - highs[i - j]) / highs[i] <= self.eq_tolerance_pct:
                    res.iloc[i, res.columns.get_loc("is_eqh")] = True
                    break

                if abs(lows[i] - lows[i - j]) / lows[i] <= self.eq_tolerance_pct:
                    res.iloc[i, res.columns.get_loc("is_eql")] = True
                    break

        return res

    def detect_liquidity_sweeps(self, df: pd.DataFrame, lookback_swings: int = 20) -> pd.DataFrame:
        """
        Detects Liquidity Sweeps / Stop Hunts.
        - Buy-Side Liquidity (BSL) Sweep: Wick penetrates Swing High, but Close remains below.
          Formula: High_t > SwingHigh and Close_t <= SwingHigh
        - Sell-Side Liquidity (SSL) Sweep: Wick penetrates Swing Low, but Close remains above.
          Formula: Low_t < SwingLow and Close_t >= SwingLow
        """
        res = df.copy()
        res["smc_liquidity_sweep"] = None

        if "swing_high" not in res.columns:
            from .structure import SMCStructureEngine
            res = SMCStructureEngine().detect_swings(res)

        highs = res["high_price"].values
        lows = res["low_price"].values
        closes = res["close_price"].values
        sh = res["swing_high"].values
        sl = res["swing_low"].values

        for i in range(1, len(res)):
            sh_prev = sh[i - 1]
            sl_prev = sl[i - 1]

            if pd.isna(sh_prev) or pd.isna(sl_prev):
                continue

            # BSL Sweep (Bearish Reversal Setup)
            if highs[i] > sh_prev and closes[i] <= sh_prev:
                res.iloc[i, res.columns.get_loc("smc_liquidity_sweep")] = "BSL_SWEEP_BEARISH"

            # SSL Sweep (Bullish Reversal Setup)
            elif lows[i] < sl_prev and closes[i] >= sl_prev:
                res.iloc[i, res.columns.get_loc("smc_liquidity_sweep")] = "SSL_SWEEP_BULLISH"

        return res
