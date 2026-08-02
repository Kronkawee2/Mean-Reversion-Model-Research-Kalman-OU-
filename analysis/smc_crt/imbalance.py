"""
SMC Imbalance Engine: Fair Value Gaps (FVG) and Liquidity Voids.

SOURCES & OFFICIAL REFERENCES:
- DYOR Academy Price Action FVG: https://dyor.net/academy/en/price_action/smart-money-concepts
- GitHub smart-money-concepts repository: https://github.com/joshyattridge/smart-money-concepts
"""

import numpy as np
import pandas as pd


class SMCImbalanceEngine:
    """Detects 3-bar Fair Value Gaps (FVG), Liquidity Voids, and tracks Mitigation state."""

    def __init__(self, min_gap_pct: float = 0.0005):
        self.min_gap_pct = min_gap_pct

    def detect_fvg(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detects 3-bar Fair Value Gaps (FVG).
        - Bullish FVG: High[i-2] < Low[i] (Gap size = Low[i] - High[i-2])
        - Bearish FVG: Low[i-2] > High[i] (Gap size = Low[i-2] - High[i])
        """
        res = df.copy()
        res["smc_fvg_type"] = None
        res["smc_fvg_top"] = np.nan
        res["smc_fvg_bottom"] = np.nan
        res["smc_fvg_size"] = 0.0
        res["smc_fvg_mitigated"] = False

        highs = res["high_price"].values
        lows = res["low_price"].values
        closes = res["close_price"].values
        n = len(res)

        for i in range(2, n):
            # Bullish FVG: High[i-2] < Low[i]
            if highs[i - 2] < lows[i]:
                gap_size = lows[i] - highs[i - 2]
                if (gap_size / closes[i]) >= self.min_gap_pct:
                    res.iloc[i, res.columns.get_loc("smc_fvg_type")] = "BULLISH_FVG"
                    res.iloc[i, res.columns.get_loc("smc_fvg_top")] = lows[i]
                    res.iloc[i, res.columns.get_loc("smc_fvg_bottom")] = highs[i - 2]
                    res.iloc[i, res.columns.get_loc("smc_fvg_size")] = gap_size

            # Bearish FVG: Low[i-2] > High[i]
            elif lows[i - 2] > highs[i]:
                gap_size = lows[i - 2] - highs[i]
                if (gap_size / closes[i]) >= self.min_gap_pct:
                    res.iloc[i, res.columns.get_loc("smc_fvg_type")] = "BEARISH_FVG"
                    res.iloc[i, res.columns.get_loc("smc_fvg_top")] = lows[i - 2]
                    res.iloc[i, res.columns.get_loc("smc_fvg_bottom")] = highs[i]
                    res.iloc[i, res.columns.get_loc("smc_fvg_size")] = gap_size

        # Track Mitigation State forward
        fvg_types = res["smc_fvg_type"].values
        fvg_tops = res["smc_fvg_top"].values
        fvg_bots = res["smc_fvg_bottom"].values

        for i in range(n):
            if fvg_types[i] is not None:
                top = fvg_tops[i]
                bot = fvg_bots[i]
                ftype = fvg_types[i]

                for j in range(i + 1, n):
                    if ftype == "BULLISH_FVG" and lows[j] <= bot:
                        res.iloc[i, res.columns.get_loc("smc_fvg_mitigated")] = True
                        break
                    elif ftype == "BEARISH_FVG" and highs[j] >= top:
                        res.iloc[i, res.columns.get_loc("smc_fvg_mitigated")] = True
                        break

        return res
