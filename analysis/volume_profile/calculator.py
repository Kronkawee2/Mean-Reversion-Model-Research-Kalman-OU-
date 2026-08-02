"""
Volume-at-Price Calculator Engine: Histogram Binning, POC, Value Area (70%), HVN & LVN.

SOURCES & OFFICIAL REFERENCES:
- NinjaTrader Volume Profile Guide: https://ninjatrader.com/futures/blogs/trade-futures-understanding-the-4-common-volume-profile-shapes/
- Trader-Dale Market & Volume Profile Books: https://www.trader-dale.com/market-profile-different-profiles-and-their-application/
- CrossTrade Learn TPO & Volume Profile: https://crosstrade.io/learn/technical-indicators/market-profile-tpo
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional


class VolumeProfileCalculator:
    """Calculates Volume-at-Price histogram, POC, Value Area (70%), HVN, and LVN."""

    def __init__(self, num_bins: int = 50, value_area_pct: float = 0.70):
        self.num_bins = num_bins
        self.value_area_pct = value_area_pct

    def compute_profile(self, df: pd.DataFrame) -> Dict:
        """
        Calculates Volume Profile metrics over the provided DataFrame.

        Returns dict containing:
        - bins: bin edges
        - bin_centers: center price of each bin
        - bin_volumes: volume accumulated at each price bin
        - poc: Point of Control (Price at max volume bin)
        - vah: Value Area High (Upper 70% boundary)
        - val: Value Area Low (Lower 70% boundary)
        - hvn: High Volume Nodes
        - lvn: Low Volume Nodes
        """
        if df.empty or len(df) < 2:
            return {
                "poc": np.nan, "vah": np.nan, "val": np.nan,
                "hvn": [], "lvn": [], "total_volume": 0.0
            }

        prices = df["close_price"].values
        volumes = df.get("volume", pd.Series([1.0] * len(df))).values

        min_p = float(prices.min())
        max_p = float(prices.max())

        if min_p == max_p:
            return {
                "poc": min_p, "vah": max_p, "val": min_p,
                "hvn": [min_p], "lvn": [], "total_volume": float(volumes.sum())
            }

        bins = np.linspace(min_p, max_p, self.num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2.0
        bin_volumes = np.zeros(self.num_bins)

        indices = np.clip(np.digitize(prices, bins) - 1, 0, self.num_bins - 1)
        for idx, vol in zip(indices, volumes):
            bin_volumes[idx] += vol

        total_volume = bin_volumes.sum()
        if total_volume == 0:
            return {
                "poc": min_p, "vah": max_p, "val": min_p,
                "hvn": [], "lvn": [], "total_volume": 0.0
            }

        # Point of Control (POC)
        poc_idx = bin_volumes.argmax()
        poc = round(float(bin_centers[poc_idx]), 5)

        # Value Area (70% total volume around POC)
        target_vol = total_volume * self.value_area_pct
        accumulated_vol = bin_volumes[poc_idx]

        left = poc_idx
        right = poc_idx

        while accumulated_vol < target_vol and (left > 0 or right < self.num_bins - 1):
            next_left_vol = bin_volumes[left - 1] if left > 0 else -1
            next_right_vol = bin_volumes[right + 1] if right < self.num_bins - 1 else -1

            if next_left_vol >= next_right_vol and left > 0:
                left -= 1
                accumulated_vol += bin_volumes[left]
            elif right < self.num_bins - 1:
                right += 1
                accumulated_vol += bin_volumes[right]

        vah = round(float(bin_centers[right]), 5)
        val = round(float(bin_centers[left]), 5)

        # High / Low Volume Nodes
        vol_mean = bin_volumes.mean()
        vol_std = bin_volumes.std()

        hvn_indices = np.where(bin_volumes >= vol_mean + vol_std)[0]
        lvn_indices = np.where(bin_volumes <= vol_mean - vol_std)[0]

        hvn = [round(float(bin_centers[i]), 5) for i in hvn_indices]
        lvn = [round(float(bin_centers[i]), 5) for i in lvn_indices]

        return {
            "bins": bins,
            "bin_centers": bin_centers,
            "bin_volumes": bin_volumes,
            "poc": poc,
            "poc_idx": poc_idx,
            "vah": vah,
            "val": val,
            "hvn": hvn,
            "lvn": lvn,
            "total_volume": float(total_volume)
        }
