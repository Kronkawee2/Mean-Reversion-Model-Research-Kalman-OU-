"""
Candle Range Theory (CRT) Engine: Asian Range Accumulation, Session Sweeps, and Premium/Discount Equilibrium.

SOURCES & OFFICIAL REFERENCES:
- CME Group FX Trading Hours & Session Liquidity Framework: https://www.cmegroup.com/
- Candle Range Theory (CRT) 3-Phase Model: Accumulation (Asian) -> Manipulation (Sweep) -> Distribution (Expansion)
"""

import numpy as np
import pandas as pd


class CRTEngine:
    """Calculates Candle Range Theory (CRT) Asian Range, Session Sweeps, and Premium/Discount Zones."""

    def __init__(self, asian_start_hour: int = 0, asian_end_hour: int = 6):
        self.asian_start_hour = asian_start_hour
        self.asian_end_hour = asian_end_hour

    def detect_session_sweeps(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates Asian Range (00:00-06:00 UTC) and detects Session Sweeps in London/NY.
        """
        res = df.copy()
        res["crt_asian_high"] = np.nan
        res["crt_asian_low"] = np.nan
        res["crt_session_sweep"] = None

        if "price_datetime" not in res.columns:
            return res

        res["dt"] = pd.to_datetime(res["price_datetime"])
        res["date"] = res["dt"].dt.date
        res["hour"] = res["dt"].dt.hour

        # Calculate Asian Range High/Low per date
        asian_mask = (res["hour"] >= self.asian_start_hour) & (res["hour"] < self.asian_end_hour)
        asian_df = res[asian_mask].groupby("date").agg(
            asian_high=("high_price", "max"),
            asian_low=("low_price", "min")
        ).reset_index()

        res = pd.merge(res, asian_df, on="date", how="left")
        res["crt_asian_high"] = res["asian_high"]
        res["crt_asian_low"] = res["asian_low"]

        # Detect London/NY Sweeps of Asian Range
        highs = res["high_price"].values
        lows = res["low_price"].values
        closes = res["close_price"].values
        ah = res["crt_asian_high"].values
        al = res["crt_asian_low"].values
        hours = res["hour"].values

        for i in range(len(res)):
            # Active in London (07:00-11:00) or NY (13:00-17:00)
            if hours[i] >= self.asian_end_hour and not pd.isna(ah[i]):
                # Sweep Asian High (Manipulation -> Bearish Setup)
                if highs[i] > ah[i] and closes[i] <= ah[i]:
                    res.iloc[i, res.columns.get_loc("crt_session_sweep")] = "ASIAN_HIGH_SWEEP_BEARISH"

                # Sweep Asian Low (Manipulation -> Bullish Setup)
                elif lows[i] < al[i] and closes[i] >= al[i]:
                    res.iloc[i, res.columns.get_loc("crt_session_sweep")] = "ASIAN_LOW_SWEEP_BULLISH"

        res.drop(columns=["dt", "date", "hour", "asian_high", "asian_low"], errors="ignore", inplace=True)
        return res

    def calc_premium_discount_equilibrium(self, df: pd.DataFrame, window: int = 50) -> pd.DataFrame:
        """
        Calculates 50% Equilibrium Median and classifies Premium vs Discount zones.
        - Premium Zone (Above 50% Median): Sell Zone.
        - Discount Zone (Below 50% Median): Buy Zone.
        - Equilibrium: 50% Median Line.
        """
        res = df.copy()
        high_n = res["high_price"].rolling(window).max()
        low_n = res["low_price"].rolling(window).min()

        res["smc_range_equilibrium"] = (high_n + low_n) / 2.0
        res["smc_zone"] = np.where(
            res["close_price"] > res["smc_range_equilibrium"],
            "PREMIUM",
            "DISCOUNT"
        )
        return res
