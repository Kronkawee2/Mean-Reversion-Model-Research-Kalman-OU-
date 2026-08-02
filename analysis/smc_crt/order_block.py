"""
SMC Order Flow Engine: Order Blocks (OB), Breaker Blocks, and Mitigation Blocks.

SOURCES & OFFICIAL REFERENCES:
- Scribd SMC OrderBlock Strategy Guide: https://www.scribd.com/document/869902609/SMC-OrderBlock-Strategy-Guide
- ACY Securities Confirmation Model: https://acy.com/en/market-news/education/confirmation-model-ob-fvg-liquidity-sweep-j-o-20251112-094218/
"""

import numpy as np
import pandas as pd


class SMCOrderBlockEngine:
    """Detects Order Blocks (OB), Breaker Blocks, and tracks active Mitigation boundaries."""

    def detect_order_blocks(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detects Order Blocks.
        - Bullish OB: Last bearish candle prior to a Bullish BOS/CHoCH.
        - Bearish OB: Last bullish candle prior to a Bearish BOS/CHoCH.
        """
        res = df.copy()
        res["smc_ob_type"] = None
        res["smc_ob_top"] = np.nan
        res["smc_ob_bottom"] = np.nan
        res["smc_ob_mitigated"] = False

        if "smc_structure_signal" not in res.columns:
            from .structure import SMCStructureEngine
            res = SMCStructureEngine().detect_bos_choch(res)

        opens = res["open_price"].values
        closes = res["close_price"].values
        highs = res["high_price"].values
        lows = res["low_price"].values
        signals = res["smc_structure_signal"].values
        n = len(res)

        for i in range(1, n):
            sig = signals[i]
            if sig in ["BULLISH_BOS", "BULLISH_CHOCH"]:
                # Look back for last bearish candle
                for j in range(i - 1, max(0, i - 10), -1):
                    if closes[j] < opens[j]:  # Bearish candle
                        res.iloc[j, res.columns.get_loc("smc_ob_type")] = "BULLISH_OB"
                        res.iloc[j, res.columns.get_loc("smc_ob_top")] = highs[j]
                        res.iloc[j, res.columns.get_loc("smc_ob_bottom")] = lows[j]
                        break

            elif sig in ["BEARISH_BOS", "BEARISH_CHOCH"]:
                # Look back for last bullish candle
                for j in range(i - 1, max(0, i - 10), -1):
                    if closes[j] > opens[j]:  # Bullish candle
                        res.iloc[j, res.columns.get_loc("smc_ob_type")] = "BEARISH_OB"
                        res.iloc[j, res.columns.get_loc("smc_ob_top")] = highs[j]
                        res.iloc[j, res.columns.get_loc("smc_ob_bottom")] = lows[j]
                        break

        # Track Mitigation Forward
        ob_types = res["smc_ob_type"].values
        ob_tops = res["smc_ob_top"].values
        ob_bots = res["smc_ob_bottom"].values

        for i in range(n):
            if ob_types[i] is not None:
                top = ob_tops[i]
                bot = ob_bots[i]
                ob_type = ob_types[i]

                for j in range(i + 1, n):
                    if ob_type == "BULLISH_OB" and lows[j] <= bot:
                        res.iloc[i, res.columns.get_loc("smc_ob_mitigated")] = True
                        break
                    elif ob_type == "BEARISH_OB" and highs[j] >= top:
                        res.iloc[i, res.columns.get_loc("smc_ob_mitigated")] = True
                        break

        return res
