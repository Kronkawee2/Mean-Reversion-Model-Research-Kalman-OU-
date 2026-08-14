"""
Indicator Feature Engine: EMA 20/50/200, ATR 14, RSI 14 (Phase 2c), OBV
(Phase 2f), and Stochastic %K/%D + CCI 20 (Phase 2g) across h1/h4/h6/d1,
persisted one row per bar per timeframe.

Reuses calc_ema / calc_rsi / calc_atr / calc_obv from
analysis.technical_analysis rather than reimplementing them here. Those
functions are the project's one EMA/RSI/ATR/OBV implementation (also used
by TechnicalAnalysisEngine.transform() and analysis/features/__init__.py's
generate_features()) — a second, parallel implementation in this module
would risk silently disagreeing with them on smoothing/cumulative
behavior, which is exactly the kind of inconsistency this project avoids
(see zone_state.py reusing structure.py/order_block.py/imbalance.py
unchanged in Phase 2a). calc_obv (technical_analysis/volume.py) already
matched the requested formula exactly — cumulative sum, +volume on a
higher close, -volume on a lower close, unchanged on an equal close — so
it's reused as-is, not reimplemented.

Stochastic and CCI have NO existing implementation anywhere in the
codebase (checked analysis/technical_analysis/*.py — momentum.py has only
RSI+MACD, no stochastic or CCI; the only textual hits for "cci" were
"Fibonacci" substring matches, not a real implementation). So — unlike
every indicator before this one — calc_stochastic/calc_cci are
implemented fresh, directly in this module, per the explicit fallback
instruction for this case.

`raw_gold`/`raw_eurusd` raw data has h1/h4/d1 tables but no populated h6 table (h6
was never actually synced by any writer — see quant_backend.py's comment
that "h6 is resampled from h1 elsewhere", which doesn't exist yet). So h6
features are computed by resampling h1 candles here, not by reading a raw
h6 table; nothing is written back to the raw `h6` table itself, since that
would be a Step 1 (raw-data) concern, not Step 2 (features).
"""

import numpy as np
import pandas as pd

from analysis.technical_analysis.trend import calc_ema
from analysis.technical_analysis.momentum import calc_rsi
from analysis.technical_analysis.volatility import calc_atr
from analysis.technical_analysis.volume import calc_obv

EMA_PERIODS = (20, 50, 200)
ATR_PERIOD = 14
RSI_PERIOD = 14
STOCH_PERIOD = 14
STOCH_SMOOTH_K = 3
STOCH_SMOOTH_D = 3
CCI_PERIOD = 20
CCI_CONSTANT = 0.015  # Lambert's original scaling constant

FEATURE_COLUMNS = [
    "symbol", "timeframe", "bar_datetime",
    "ema_20", "ema_50", "ema_200", "atr_14", "rsi_14", "obv",
    "stoch_k", "stoch_d", "cci_20",
]


def calc_stochastic(df: pd.DataFrame, period: int = STOCH_PERIOD,
                     smooth_k: int = STOCH_SMOOTH_K, smooth_d: int = STOCH_SMOOTH_D) -> pd.DataFrame:
    """
    Stochastic Oscillator (Lane, 1950s).
    Formula:
      Raw %K = 100 * (Close - Lowest_Low_N) / (Highest_High_N - Lowest_Low_N)
      %K (Slow/displayed) = SMA(Raw %K, smooth_k)
      %D                  = SMA(%K, smooth_d)
    period=14, smooth_k=3, smooth_d=3 is the "Slow Stochastic (14,3,3)"
    convention — the default on TradingView and most retail platforms —
    chosen specifically so a real-chart cross-check lines up with what a
    trader would actually see rather than an unsmoothed Fast %K.
    Overbought: %K > 80  |  Oversold: %K < 20
    """
    low_n = df["low_price"].rolling(period).min()
    high_n = df["high_price"].rolling(period).max()
    raw_k = 100.0 * (df["close_price"] - low_n) / (high_n - low_n).replace(0, pd.NA)

    k = raw_k.rolling(smooth_k).mean()
    d = k.rolling(smooth_d).mean()

    return pd.DataFrame({"stoch_k": k.round(3), "stoch_d": d.round(3)})


def calc_cci(df: pd.DataFrame, period: int = CCI_PERIOD) -> pd.Series:
    """
    Commodity Channel Index (Lambert, 1980).
    Formula:
      Typical Price (TP) = (High + Low + Close) / 3
      CCI = (TP - SMA(TP, period)) / (0.015 * MeanAbsDev(TP, period))
    Overbought: CCI > 100  |  Oversold: CCI < -100
    """
    tp = (df["high_price"] + df["low_price"] + df["close_price"]) / 3.0
    sma_tp = tp.rolling(period).mean()
    mean_abs_dev = tp.rolling(period).apply(lambda w: np.abs(w - w.mean()).mean(), raw=True)

    cci = (tp - sma_tp) / (CCI_CONSTANT * mean_abs_dev.replace(0, pd.NA))
    return cci.round(3)


def resample_ohlc(df: pd.DataFrame, rule: str = "6h") -> pd.DataFrame:
    """
    Resamples h1 (or finer) OHLC into coarser candles (default 6h: 1h->6h).
    origin='start_day' anchors buckets to UTC midnight of the first bar's
    calendar day, so 6h buckets land on 00/06/12/18 UTC every day (24 is
    evenly divisible by 6, so this holds for every subsequent day too) —
    matching how MT5/most brokers define H6 candles.
    """
    base = df.reset_index(drop=True).copy()
    base["price_datetime"] = pd.to_datetime(base["price_datetime"])
    base = base.set_index("price_datetime").sort_index()

    agg = {
        "open_price": "first",
        "high_price": "max",
        "low_price": "min",
        "close_price": "last",
    }
    if "volume" in base.columns:
        agg["volume"] = "sum"

    resampled = base.resample(rule, origin="start_day").agg(agg).dropna(subset=["open_price"])
    return resampled.reset_index()


def calc_indicator_features(df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
    """
    df: OHLC(V) with price_datetime, open_price, high_price, low_price,
    close_price, sorted ascending; volume is required for OBV (both
    MT5-sourced and Yahoo-sourced raw tables already normalize to a
    single `volume` column upstream — see run_volume_profile.py's module
    docstring for the same point made about Volume Profile). Returns one
    row per bar: EMA 20/50/200, ATR 14, RSI 14, OBV, Stochastic %K/%D, CCI 20.
    """
    if df.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    base = df.reset_index(drop=True).copy()
    base["price_datetime"] = pd.to_datetime(base["price_datetime"])
    for col in ("open_price", "high_price", "low_price", "close_price"):
        base[col] = base[col].astype(float)
    if "volume" in base.columns:
        base["volume"] = base["volume"].astype(float)

    out = pd.DataFrame({
        "symbol": symbol,
        "timeframe": timeframe,
        "bar_datetime": base["price_datetime"],
    })
    for period in EMA_PERIODS:
        out[f"ema_{period}"] = calc_ema(base["close_price"], period)
    out["atr_14"] = calc_atr(base, ATR_PERIOD)
    out["rsi_14"] = calc_rsi(base["close_price"], RSI_PERIOD)
    out["obv"] = calc_obv(base)

    stoch = calc_stochastic(base)
    out["stoch_k"] = stoch["stoch_k"]
    out["stoch_d"] = stoch["stoch_d"]
    out["cci_20"] = calc_cci(base)

    return out[FEATURE_COLUMNS]
