"""
Smart Money Concepts (SMC) & Candle Range Theory (CRT) Engine.
Algorithmic detection of BOS, CHoCH, FVG, Order Blocks, Liquidity Sweeps, and CRT Asian Session Sweeps.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional


class SMCEngine:
    """Detects Smart Money Concepts (BOS, CHoCH, FVG, Order Blocks, Liquidity Sweeps)."""

    def detect_fvg(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect Fair Value Gaps (3-candle imbalance).
        Bullish FVG: Low[i] > High[i-2]
        Bearish FVG: High[i] < Low[i-2]
        """
        res = df.copy()
        res['fvg_type'] = None
        res['fvg_top'] = np.nan
        res['fvg_bottom'] = np.nan

        high = res['high_price'].values
        low = res['low_price'].values

        for i in range(2, len(res)):
            # Bullish FVG
            if low[i] > high[i - 2]:
                res.iloc[i, res.columns.get_loc('fvg_type')] = 'BULLISH'
                res.iloc[i, res.columns.get_loc('fvg_top')] = low[i]
                res.iloc[i, res.columns.get_loc('fvg_bottom')] = high[i - 2]
            # Bearish FVG
            elif high[i] < low[i - 2]:
                res.iloc[i, res.columns.get_loc('fvg_type')] = 'BEARISH'
                res.iloc[i, res.columns.get_loc('fvg_top')] = low[i - 2]
                res.iloc[i, res.columns.get_loc('fvg_bottom')] = high[i]

        return res

    def detect_swing_points(self, df: pd.DataFrame, window: int = 3) -> pd.DataFrame:
        """Detect swing highs and swing lows using a rolling window."""
        res = df.copy()
        high = res['high_price']
        low = res['low_price']

        res['is_swing_high'] = False
        res['is_swing_low'] = False

        for i in range(window, len(df) - window):
            if high.iloc[i] == high.iloc[i - window:i + window + 1].max():
                res.iloc[i, res.columns.get_loc('is_swing_high')] = True
            if low.iloc[i] == low.iloc[i - window:i + window + 1].min():
                res.iloc[i, res.columns.get_loc('is_swing_low')] = True

        return res

    def detect_bos_choch(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect Break of Structure (BOS) and Change of Character (CHoCH).
        BOS: Continuation break of recent swing high/low in direction of trend.
        CHoCH: Reversal break of recent opposite swing high/low.
        """
        res = self.detect_swing_points(df)
        res['structure_signal'] = None

        last_swing_high = None
        last_swing_low = None
        current_trend = None  # 'BULLISH' or 'BEARISH'

        for i in range(len(res)):
            c_close = res['close_price'].iloc[i]

            if res['is_swing_high'].iloc[i]:
                last_swing_high = res['high_price'].iloc[i]
            if res['is_swing_low'].iloc[i]:
                last_swing_low = res['low_price'].iloc[i]

            # Bullish Break
            if last_swing_high is not None and c_close > last_swing_high:
                if current_trend == 'BEARISH':
                    res.iloc[i, res.columns.get_loc('structure_signal')] = 'BULLISH_CHOCH'
                    current_trend = 'BULLISH'
                elif current_trend == 'BULLISH':
                    res.iloc[i, res.columns.get_loc('structure_signal')] = 'BULLISH_BOS'
                else:
                    current_trend = 'BULLISH'
                last_swing_high = None

            # Bearish Break
            elif last_swing_low is not None and c_close < last_swing_low:
                if current_trend == 'BULLISH':
                    res.iloc[i, res.columns.get_loc('structure_signal')] = 'BEARISH_CHOCH'
                    current_trend = 'BEARISH'
                elif current_trend == 'BEARISH':
                    res.iloc[i, res.columns.get_loc('structure_signal')] = 'BEARISH_BOS'
                else:
                    current_trend = 'BEARISH'
                last_swing_low = None

        return res


class CRTEngine:
    """Candle Range Theory (CRT) Engine — Session Asian Range & Sweeps."""

    def calc_asian_range(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate Asian Session High/Low (00:00 to 06:00 UTC).
        Annotates session range for each trading day.
        """
        res = df.copy()
        if 'price_datetime' not in res.columns:
            return res

        res['price_datetime'] = pd.to_datetime(res['price_datetime'])
        res['hour'] = res['price_datetime'].dt.hour
        res['date'] = res['price_datetime'].dt.date

        asian_mask = (res['hour'] >= 0) & (res['hour'] < 6)
        asian_df = res[asian_mask]

        session_stats = asian_df.groupby('date').agg(
            asian_high=('high_price', 'max'),
            asian_low=('low_price', 'min')
        ).reset_index()

        res = res.merge(session_stats, on='date', how='left')
        res['asian_mid'] = (res['asian_high'] + res['asian_low']) / 2

        return res

    def detect_session_sweeps(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Detect London/NY sweeps of Asian High/Low.
        Sweep occurs when wick breaks Asian High/Low but close returns inside.
        """
        res = self.calc_asian_range(df)
        res['sweep_signal'] = None

        for i in range(len(res)):
            row = res.iloc[i]
            if pd.isna(row.get('asian_high')) or row['hour'] < 6:
                continue

            # Bullish Sweep (Liquidity Sweep below Asian Low)
            if row['low_price'] < row['asian_low'] and row['close_price'] > row['asian_low']:
                res.iloc[i, res.columns.get_loc('sweep_signal')] = 'BULLISH_ASIAN_SWEEP'
            # Bearish Sweep (Liquidity Sweep above Asian High)
            elif row['high_price'] > row['asian_high'] and row['close_price'] < row['asian_high']:
                res.iloc[i, res.columns.get_loc('sweep_signal')] = 'BEARISH_ASIAN_SWEEP'

        return res


if __name__ == "__main__":
    # Smoke test
    dates = pd.date_range("2026-07-27 00:00", periods=48, freq="15min")
    np.random.seed(42)
    prices = 2000 + np.cumsum(np.random.randn(48) * 2)

    df = pd.DataFrame({
        "price_datetime": dates,
        "open_price": prices - 0.5,
        "high_price": prices + 1.5,
        "low_price": prices - 1.5,
        "close_price": prices,
        "volume": 1000
    })

    smc = SMCEngine()
    df_fvg = smc.detect_fvg(df)
    df_bos = smc.detect_bos_choch(df_fvg)

    crt = CRTEngine()
    df_crt = crt.detect_session_sweeps(df_bos)

    print("SMC/CRT Engine Smoke Test Passed.")
    print("Columns:", [c for c in df_crt.columns if 'fvg' in c or 'sweep' in c or 'structure' in c])
