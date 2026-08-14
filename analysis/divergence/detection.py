"""
Divergence Detection Engine.

SOURCES & OFFICIAL REFERENCES:
1. Corporate Finance Institute (CFI): https://corporatefinanceinstitute.com/resources/career-map/sell-side/capital-markets/divergence/
2. Investopedia Divergence Trading Guide: https://www.investopedia.com/terms/d/divergence.asp
3. UHAS Technical Analysis & Divergence Guide: https://uhas.com/what-is-divergence-forex/
4. LiteFinance Divergence Trading Strategy: https://www.litefinance.org/th/blog/for-professionals/divergence-ni-fxreks-kar-therd-baeb-divergence-khux-xari-laea-thanganyangri/
5. JustMarkets Divergence Learning Guide: https://justmarkets.com/th/trading-articles/learning/what-is-divergence-and-how-to-use-it
6. WikiFX Divergence Usage: https://www.wikifx.com/th/learn/202405145244267079.html
7. CFTC Commitment of Traders (COT): https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from .feature_engineering import DivergenceFeatureEngine


def find_price_pivots(
    prices: np.ndarray,
    indicators: np.ndarray,
    window: int,
) -> Tuple[List[Tuple[int, float, float]], List[Tuple[int, float, float]]]:
    """
    Finds causal (confirmed only once `window` future bars are known) price
    pivot lows/highs, pairing each pivot bar with the indicator's value at
    that same bar index. This is the shared primitive behind both
    DivergenceDetector.detect_technical_divergence (Regular + Hidden,
    annotates a DataFrame column) and
    analysis.divergence.technical_divergence_state (Regular only this
    pass, persists structured pivot-pair rows) — extracted here so there
    is exactly one pivot-finding implementation, not two that could drift
    apart. Pivots are found on price only; divergence compares the
    indicator's value at those same price-pivot bars, which is the
    standard approach (independently pivoting the indicator too and then
    trying to time-match two separate pivot series is fragile and not how
    divergence is normally read).

    Returns (pivots_low, pivots_high), each a list of
    (bar_index, price, indicator_value) tuples.
    """
    n = len(prices)
    w = window
    pivots_low = []
    pivots_high = []

    for i in range(w, n - w):
        if all(prices[i] <= prices[i - j] for j in range(1, w + 1)) and \
           all(prices[i] <= prices[i + j] for j in range(1, w + 1)):
            pivots_low.append((i, prices[i], indicators[i]))

        if all(prices[i] >= prices[i - j] for j in range(1, w + 1)) and \
           all(prices[i] >= prices[i + j] for j in range(1, w + 1)):
            pivots_high.append((i, prices[i], indicators[i]))

    return pivots_low, pivots_high


class DivergenceDetector:
    """
    Causal, zero look-ahead bias divergence detection algorithms.
    Ref: CFI & Investopedia Divergence Definitions
    """

    def __init__(self, pivot_window: int = 3):
        self.pivot_window = pivot_window
        self.feature_engine = DivergenceFeatureEngine()

    def detect_technical_divergence(
        self,
        df: pd.DataFrame,
        indicator_col: str = "rsi_14",
        price_col: str = "close_price"
    ) -> pd.DataFrame:
        """
        Detects Regular (Reversal) and Hidden (Continuation) divergences.
        Source: CFI & Investopedia Technical Divergence Definitions

        FORMULAS & DEFINITIONS:
        - REGULAR_BULLISH (Reversal): Price Lower Low (LL), Indicator Higher Low (HL)
        - REGULAR_BEARISH (Reversal): Price Higher High (HH), Indicator Lower High (LH)
        - HIDDEN_BULLISH (Continuation): Price Higher Low (HL), Indicator Lower Low (LL)
        - HIDDEN_BEARISH (Continuation): Price Lower High (LH), Indicator Higher High (HH)
        """
        res = df.copy()
        res[f"div_{indicator_col}_signal"] = None

        if indicator_col not in res.columns or price_col not in res.columns:
            return res

        prices = res[price_col].values
        indicators = res[indicator_col].values
        n = len(res)

        w = self.pivot_window
        pivots_low, pivots_high = find_price_pivots(prices, indicators, w)

        # Compare consecutive low pivots (Bullish Divergences)
        for k in range(1, len(pivots_low)):
            idx_curr, p_curr, i_curr = pivots_low[k]
            idx_prev, p_prev, i_prev = pivots_low[k - 1]

            signal_idx = idx_curr + w  # Signal confirmed at right boundary
            if signal_idx >= n:
                continue

            # Regular Bullish: Price LL, Indicator HL
            if p_curr < p_prev and i_curr > i_prev:
                res.iloc[signal_idx, res.columns.get_loc(f"div_{indicator_col}_signal")] = "REGULAR_BULLISH"
            # Hidden Bullish: Price HL, Indicator LL
            elif p_curr > p_prev and i_curr < i_prev:
                res.iloc[signal_idx, res.columns.get_loc(f"div_{indicator_col}_signal")] = "HIDDEN_BULLISH"

        # Compare consecutive high pivots (Bearish Divergences)
        for k in range(1, len(pivots_high)):
            idx_curr, p_curr, i_curr = pivots_high[k]
            idx_prev, p_prev, i_prev = pivots_high[k - 1]

            signal_idx = idx_curr + w
            if signal_idx >= n:
                continue

            # Regular Bearish: Price HH, Indicator LH
            if p_curr > p_prev and i_curr < i_prev:
                res.iloc[signal_idx, res.columns.get_loc(f"div_{indicator_col}_signal")] = "REGULAR_BEARISH"
            # Hidden Bearish: Price LH, Indicator HH
            elif p_curr < p_prev and i_curr > i_prev:
                res.iloc[signal_idx, res.columns.get_loc(f"div_{indicator_col}_signal")] = "HIDDEN_BEARISH"

        return res

    def detect_intermarket_divergence(
        self,
        df_asset: pd.DataFrame,
        driver_close_col: str = "dxy_close",
        asset_close_col: str = "close_price",
        expected_relationship: str = "inverse"
    ) -> pd.DataFrame:
        """
        Detects Inter-Market Macro Divergence (e.g. Gold vs DXY or Gold vs GDX Miners).
        Source: CME Group Intermarket Relationships & Institutional Macro Analysis
        
        RELATIONSHIPS:
        - 'inverse': Asset and Driver move in opposite directions (e.g., Gold vs DXY).
          Inter-market Bullish: Driver HH, but Asset fails to make LL (Gold Resilience).
          Inter-market Bearish: Driver LL, but Asset fails to make HH (Gold Weakness).
        - 'direct': Asset and Driver move in same direction (e.g., Gold vs GDX Gold Miners).
          Miners Bearish Divergence: Asset (Gold) HH, but Driver (GDX) LH (Miners leading lower).
        """
        res = df_asset.copy()
        driver_name = driver_close_col.replace("_close", "")
        signal_col = f"div_intermarket_{driver_name}"
        res[signal_col] = None

        if driver_close_col not in res.columns or asset_close_col not in res.columns:
            return res

        asset_p = res[asset_close_col].values
        driver_p = res[driver_close_col].values
        n = len(res)

        w = self.pivot_window

        for i in range(w * 2, n):
            a_curr, a_prev = asset_p[i], asset_p[i - w]
            d_curr, d_prev = driver_p[i], driver_p[i - w]

            if pd.isna(d_curr) or pd.isna(d_prev):
                continue

            if expected_relationship == "inverse":
                # DXY HH but Gold failed LL -> Bullish Gold
                if d_curr > d_prev and a_curr >= a_prev:
                    res.iloc[i, res.columns.get_loc(signal_col)] = "INTERMARKET_BULLISH"
                # DXY LL but Gold failed HH -> Bearish Gold
                elif d_curr < d_prev and a_curr <= a_prev:
                    res.iloc[i, res.columns.get_loc(signal_col)] = "INTERMARKET_BEARISH"

            elif expected_relationship == "direct":
                # Gold HH but GDX LH -> Bearish Divergence
                if a_curr > a_prev and d_curr < d_prev:
                    res.iloc[i, res.columns.get_loc(signal_col)] = "MINERS_BEARISH_DIV"
                # Gold LL but GDX HL -> Bullish Divergence
                elif a_curr < a_prev and d_curr > d_prev:
                    res.iloc[i, res.columns.get_loc(signal_col)] = "MINERS_BULLISH_DIV"

        return res

    def detect_cot_divergence(
        self,
        df: pd.DataFrame,
        comm_net_col: str = "comm_net_pos",
        price_col: str = "close_price",
        lookback_bars: int = 52
    ) -> pd.DataFrame:
        """
        Detects Institutional CFTC COT Divergence.
        Source: CFTC Commitment of Traders (COT) Analysis
        URL: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
        
        LOGIC:
        Fires when Price reaches a multi-week extreme while Commercial Net Longs fail to confirm
        (Smart money / Commercial Hedgers distributing into price strength).
        """
        res = df.copy()
        res["div_cot_signal"] = None

        if comm_net_col not in res.columns or price_col not in res.columns:
            return res

        price_max = res[price_col].rolling(lookback_bars).max()
        price_min = res[price_col].rolling(lookback_bars).min()

        comm_max = res[comm_net_col].rolling(lookback_bars).max()
        comm_min = res[comm_net_col].rolling(lookback_bars).min()

        for i in range(lookback_bars, len(res)):
            p_curr = res[price_col].iloc[i]
            c_curr = res[comm_net_col].iloc[i]

            # Price at 52w High, but Commercial Position not at 52w High (Smart money distributing)
            if p_curr >= price_max.iloc[i] and c_curr < comm_max.iloc[i] * 0.9:
                res.iloc[i, res.columns.get_loc("div_cot_signal")] = "COT_BEARISH_DIV"
            # Price at 52w Low, but Commercial Position not at 52w Low (Smart money accumulating)
            elif p_curr <= price_min.iloc[i] and c_curr > comm_min.iloc[i] * 1.1:
                res.iloc[i, res.columns.get_loc("div_cot_signal")] = "COT_BULLISH_DIV"

        return res
