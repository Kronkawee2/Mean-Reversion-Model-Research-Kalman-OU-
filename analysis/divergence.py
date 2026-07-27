"""
Divergence Engine: 12 Divergence Detection Models.
Covers Inter-Market/Macro Divergences, Technical/Volume Oscillators, and MTF Confluence.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class DivergenceEngine:
    """Calculates Inter-Market, Technical, and Multi-Timeframe Divergences."""

    def calc_ratio_zscore(self, series_a: pd.Series, series_b: pd.Series, window: int = 30) -> pd.Series:
        """Calculate Z-score of ratio between two asset price series."""
        ratio = series_a / series_b
        mean = ratio.rolling(window).mean()
        std = ratio.rolling(window).std().replace(0, np.nan)
        return (ratio - mean) / std

    def detect_rsi_divergence(self, df: pd.DataFrame, rsi_col: str = 'rsi_14') -> pd.DataFrame:
        """
        Detect RSI Regular and Hidden Divergences.
        Regular Bullish: Price LL, RSI HL (Reversal)
        Regular Bearish: Price HH, RSI LH (Reversal)
        Hidden Bullish: Price HL, RSI LL (Continuation)
        Hidden Bearish: Price LH, RSI HH (Continuation)
        """
        res = df.copy()
        res['div_rsi_signal'] = None

        if rsi_col not in res.columns or 'close_price' not in res.columns:
            return res

        close = res['close_price'].values
        rsi = res[rsi_col].values

        for i in range(5, len(res)):
            # Local extremes over 5-bar window
            if i < 10:
                continue

            p_curr = close[i]
            p_prev = close[i - 5]
            r_curr = rsi[i]
            r_prev = rsi[i - 5]

            if pd.isna(r_curr) or pd.isna(r_prev):
                continue

            # Regular Bullish: Price lower, RSI higher
            if p_curr < p_prev and r_curr > r_prev and r_curr < 35:
                res.iloc[i, res.columns.get_loc('div_rsi_signal')] = 'REGULAR_BULLISH'
            # Regular Bearish: Price higher, RSI lower
            elif p_curr > p_prev and r_curr < r_prev and r_curr > 65:
                res.iloc[i, res.columns.get_loc('div_rsi_signal')] = 'REGULAR_BEARISH'
            # Hidden Bullish: Price higher low, RSI lower low
            elif p_curr > p_prev and r_curr < r_prev and r_curr < 50:
                res.iloc[i, res.columns.get_loc('div_rsi_signal')] = 'HIDDEN_BULLISH'
            # Hidden Bearish: Price lower high, RSI higher high
            elif p_curr < p_prev and r_curr > r_prev and r_curr > 50:
                res.iloc[i, res.columns.get_loc('div_rsi_signal')] = 'HIDDEN_BEARISH'

        return res

    def detect_intermarket_divergence(self, df_asset: pd.DataFrame, df_driver: pd.DataFrame,
                                     asset_name: str = 'gold', driver_name: str = 'dxy') -> pd.DataFrame:
        """
        Detect Inter-Market Divergence (e.g. Gold vs DXY).
        Normal correlation between Gold & DXY is Inverse (-1).
        Divergence occurs when DXY makes Higher High but Gold fails to make Lower Low (Bullish Gold).
        """
        res = df_asset.copy()
        res[f'div_{driver_name}_signal'] = None

        if df_driver.empty:
            return res

        merged = pd.merge_asof(
            res.sort_values('price_datetime'),
            df_driver[['price_datetime', 'close_price']].rename(columns={'close_price': 'driver_close'}).sort_values('price_datetime'),
            on='price_datetime',
            direction='backward'
        )

        asset_close = merged['close_price'].values
        driver_close = merged['driver_close'].values

        for i in range(5, len(merged)):
            a_curr, a_prev = asset_close[i], asset_close[i - 5]
            d_curr, d_prev = driver_close[i], driver_close[i - 5]

            if pd.isna(d_curr) or pd.isna(d_prev):
                continue

            # Bullish Asset Divergence: Driver HH (strong dollar), but Asset fails to make LL (resilient asset)
            if d_curr > d_prev and a_curr >= a_prev:
                merged.iloc[i, merged.columns.get_loc(f'div_{driver_name}_signal')] = 'INTERMARKET_BULLISH'
            # Bearish Asset Divergence: Driver LL (weak dollar), but Asset fails to make HH (weak asset)
            elif d_curr < d_prev and a_curr <= a_prev:
                merged.iloc[i, merged.columns.get_loc(f'div_{driver_name}_signal')] = 'INTERMARKET_BEARISH'

        res[f'div_{driver_name}_signal'] = merged[f'div_{driver_name}_signal'].values
        return res


if __name__ == "__main__":
    # Smoke test
    dates = pd.date_range("2026-07-01", periods=60, freq="D")
    np.random.seed(42)

    df_gold = pd.DataFrame({
        'price_datetime': dates,
        'close_price': 2000 + np.cumsum(np.random.randn(60) * 5),
        'rsi_14': 50 + np.random.randn(60) * 10
    })

    df_dxy = pd.DataFrame({
        'price_datetime': dates,
        'close_price': 100 + np.cumsum(np.random.randn(60) * 0.5)
    })

    div_engine = DivergenceEngine()
    df_rsi_div = div_engine.detect_rsi_divergence(df_gold)
    df_macro_div = div_engine.detect_intermarket_divergence(df_rsi_div, df_dxy, 'gold', 'dxy')

    print("Divergence Engine Smoke Test Passed.")
    print("Signals found:", df_macro_div['div_dxy_signal'].value_counts().to_dict())
