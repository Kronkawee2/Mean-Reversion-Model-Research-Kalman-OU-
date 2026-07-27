"""
Feature Engineering module for Multi-Timeframe Quant Data.
Calculates technical features (EMA 20/50/200, ATR 14, RSI 14, Log Returns).
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    # Wilder smoothing
    for i in range(period, len(series)):
        avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
        avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['high_price']
    low = df['low_price']
    close = df['close_price']

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


def generate_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate core features from OHLCV DataFrame.
    Expects columns: open_price, high_price, low_price, close_price, volume
    """
    if df.empty or len(df) < 5:
        return df

    res = df.copy()
    close = res['close_price']

    # Returns
    res['log_return'] = np.log(close / close.shift(1))
    res['pct_change'] = close.pct_change()

    # EMAs
    res['ema_20'] = calc_ema(close, 20)
    res['ema_50'] = calc_ema(close, 50)
    res['ema_200'] = calc_ema(close, 200)

    # Momentum & Volatility
    res['rsi_14'] = calc_rsi(close, 14)
    res['atr_14'] = calc_atr(res, 14)
    res['volatility_20'] = res['log_return'].rolling(20).std()

    # Price distance to EMAs (%)
    res['dist_ema_20'] = (close - res['ema_20']) / res['ema_20']
    res['dist_ema_50'] = (close - res['ema_50']) / res['ema_50']
    res['dist_ema_200'] = (close - res['ema_200']) / res['ema_200']

    return res


if __name__ == "__main__":
    # Smoke test
    dates = pd.date_range("2026-01-01", periods=100, freq="1h")
    np.random.seed(42)
    close = 2000 + np.cumsum(np.random.randn(100) * 3)

    sample_df = pd.DataFrame({
        "price_datetime": dates,
        "open_price": close - 1,
        "high_price": close + 2,
        "low_price": close - 2,
        "close_price": close,
        "volume": np.random.randint(100, 5000, 100)
    })

    feats = generate_features(sample_df)
    print("Features generated successfully. Shape:", feats.shape)
    print("Columns:", list(feats.columns))
