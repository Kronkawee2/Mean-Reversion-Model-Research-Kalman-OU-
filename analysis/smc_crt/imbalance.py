"""
SMC Imbalance Engine: Fair Value Gaps (FVG) and Liquidity Voids.

SOURCES & OFFICIAL REFERENCES:
- DYOR Academy Price Action FVG: https://dyor.net/academy/en/price_action/smart-money-concepts
- GitHub smart-money-concepts repository: https://github.com/joshyattridge/smart-money-concepts
"""

import numpy as np
import pandas as pd

# Phase 2a validation against real gold h1 data showed the fixed
# gap-size-as-%-of-close filter (old default 0.05%) let through a lot of
# noise: it doesn't adapt to the instrument's actual volatility, so it
# over-qualifies gaps during quiet stretches and under-qualifies nothing
# during volatile ones. True ATR isn't computed anywhere upstream of this
# module yet, so we approximate it with a rolling mean of recent candle
# ranges (high - low) as the volatility proxy, and require the gap to be at
# least this fraction of that proxy to count as a real FVG.
FVG_MIN_GAP_ATR_MULT = 0.5
FVG_ATR_PROXY_WINDOW = 14


class SMCImbalanceEngine:
    """Detects 3-bar Fair Value Gaps (FVG), Liquidity Voids, and tracks Mitigation state."""

    def __init__(
        self,
        min_gap_atr_mult: float = FVG_MIN_GAP_ATR_MULT,
        atr_proxy_window: int = FVG_ATR_PROXY_WINDOW,
    ):
        self.min_gap_atr_mult = min_gap_atr_mult
        self.atr_proxy_window = atr_proxy_window

    def detect_fvg(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detects 3-bar Fair Value Gaps (FVG).
        - Bullish FVG: High[i-2] < Low[i] (Gap size = Low[i] - High[i-2])
        - Bearish FVG: Low[i-2] > High[i] (Gap size = Low[i-2] - High[i])

        A candidate gap only qualifies as an FVG if its size is at least
        FVG_MIN_GAP_ATR_MULT times the average recent candle range (the ATR
        proxy), filtering out the noise-sized gaps that are routine in any
        volatility regime rather than genuine imbalances.
        """
        res = df.copy()
        res["smc_fvg_type"] = None
        res["smc_fvg_top"] = np.nan
        res["smc_fvg_bottom"] = np.nan
        res["smc_fvg_size"] = 0.0
        res["smc_fvg_mitigated"] = False

        highs = res["high_price"].values
        lows = res["low_price"].values
        n = len(res)

        atr_proxy = (
            (res["high_price"] - res["low_price"])
            .rolling(self.atr_proxy_window, min_periods=1)
            .mean()
            .values
        )

        for i in range(2, n):
            min_gap_size = self.min_gap_atr_mult * atr_proxy[i - 1]

            # Bullish FVG: High[i-2] < Low[i]
            if highs[i - 2] < lows[i]:
                gap_size = lows[i] - highs[i - 2]
                if gap_size >= min_gap_size:
                    res.iloc[i, res.columns.get_loc("smc_fvg_type")] = "BULLISH_FVG"
                    res.iloc[i, res.columns.get_loc("smc_fvg_top")] = lows[i]
                    res.iloc[i, res.columns.get_loc("smc_fvg_bottom")] = highs[i - 2]
                    res.iloc[i, res.columns.get_loc("smc_fvg_size")] = gap_size

            # Bearish FVG: Low[i-2] > High[i]
            elif lows[i - 2] > highs[i]:
                gap_size = lows[i - 2] - highs[i]
                if gap_size >= min_gap_size:
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
