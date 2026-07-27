"""
Volume Profile Engine.
Calculates Point of Control (POC), Value Area High (VAH), Value Area Low (VAL),
High Volume Nodes (HVN), and Low Volume Nodes (LVN) from OHLCV data.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple


class VolumeProfileEngine:
    """Calculates Volume Profile metrics using price binning and volume distribution."""

    def __init__(self, num_bins: int = 50, value_area_pct: float = 0.70):
        self.num_bins = num_bins
        self.value_area_pct = value_area_pct

    def compute_profile(self, df: pd.DataFrame) -> Dict:
        """
        Compute Volume Profile for a given DataFrame of OHLCV candles.
        Returns POC, VAH, VAL, HVN list, and LVN list.
        """
        if df.empty or 'close_price' not in df.columns or len(df) < 5:
            return {
                'poc': None, 'vah': None, 'val': None,
                'hvn': [], 'lvn': []
            }

        prices = df['close_price'].values
        volumes = df['volume'].values

        min_p = prices.min()
        max_p = prices.max()

        if min_p == max_p:
            return {
                'poc': min_p, 'vah': max_p, 'val': min_p,
                'hvn': [min_p], 'lvn': []
            }

        bins = np.linspace(min_p, max_p, self.num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        bin_volumes = np.zeros(self.num_bins)

        # Distribute volume into price bins
        indices = np.digitize(prices, bins) - 1
        indices = np.clip(indices, 0, self.num_bins - 1)

        for idx, vol in zip(indices, volumes):
            bin_volumes[idx] += vol

        total_volume = bin_volumes.sum()
        if total_volume == 0:
            return {
                'poc': min_p, 'vah': max_p, 'val': min_p,
                'hvn': [], 'lvn': []
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
            else:
                break

        val = round(float(bin_centers[left]), 5)
        vah = round(float(bin_centers[right]), 5)

        # High Volume Nodes (peaks) and Low Volume Nodes (troughs)
        hvn = []
        lvn = []

        for i in range(1, self.num_bins - 1):
            if bin_volumes[i] > bin_volumes[i - 1] and bin_volumes[i] > bin_volumes[i + 1]:
                if bin_volumes[i] > total_volume * 0.05:
                    hvn.append(round(float(bin_centers[i]), 5))
            elif bin_volumes[i] < bin_volumes[i - 1] and bin_volumes[i] < bin_volumes[i + 1]:
                lvn.append(round(float(bin_centers[i]), 5))

        return {
            'poc': poc,
            'vah': vah,
            'val': val,
            'hvn': hvn,
            'lvn': lvn
        }


if __name__ == "__main__":
    # Smoke test
    prices = 2000 + np.random.randn(200) * 10
    vols = np.random.randint(100, 10000, 200)

    df_test = pd.DataFrame({'close_price': prices, 'volume': vols})
    engine = VolumeProfileEngine()
    profile = engine.compute_profile(df_test)

    print("Volume Profile Smoke Test:")
    print("POC:", profile['poc'])
    print("VAH:", profile['vah'])
    print("VAL:", profile['val'])
    print("HVN count:", len(profile['hvn']))
    print("LVN count:", len(profile['lvn']))
