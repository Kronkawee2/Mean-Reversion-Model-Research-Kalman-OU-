"""
Support & Resistance: Fibonacci Retracement and Swing-based S/R Zone Detection.

SOURCES & OFFICIAL REFERENCES:
- Investopedia Fibonacci: https://www.investopedia.com/terms/f/fibonacciretracement.asp
- FXFoundations Technical Analysis: https://fxfoundations.com/learn/technical-analysis/technical-indicators
- NCFE Technical Analysis Indicators: https://ncfe.org.in/wp-content/uploads/2023/12/Technical-analysis-Indicators.pdf
"""

import numpy as np
import pandas as pd
from typing import Dict, List


FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]


def calc_fibonacci_levels(swing_high: float, swing_low: float) -> Dict[str, float]:
    """
    Fibonacci Retracement Levels.
    Formula (Downswing): Level = High - (High - Low) * ratio
    Key levels: 23.6%, 38.2%, 50%, 61.8% (Golden Ratio), 78.6%
    """
    diff = swing_high - swing_low
    return {
        f"fib_{int(r * 1000)}": round(swing_high - diff * r, 5)
        for r in FIB_LEVELS
    }


def detect_sr_zones(df: pd.DataFrame, window: int = 20, tolerance_pct: float = 0.002) -> List[Dict]:
    """
    Detects significant Support/Resistance zones from Swing Highs and Swing Lows.
    A zone is confirmed when 2+ swing highs/lows cluster within tolerance_pct.
    tolerance_pct = 0.2% by default.
    """
    highs = df["high_price"].values
    lows = df["low_price"].values
    n = len(df)

    swings = []
    for i in range(window, n - window):
        if all(highs[i] >= highs[i - j] for j in range(1, window + 1)) and \
           all(highs[i] >= highs[i + j] for j in range(1, window + 1)):
            swings.append({"price": highs[i], "type": "RESISTANCE", "idx": i})
        if all(lows[i] <= lows[i - j] for j in range(1, window + 1)) and \
           all(lows[i] <= lows[i + j] for j in range(1, window + 1)):
            swings.append({"price": lows[i], "type": "SUPPORT", "idx": i})

    # Cluster swings within tolerance
    zones = []
    used = set()
    for i, s in enumerate(swings):
        if i in used:
            continue
        cluster = [s]
        for j, t in enumerate(swings):
            if j != i and j not in used:
                if abs(s["price"] - t["price"]) / s["price"] <= tolerance_pct:
                    cluster.append(t)
                    used.add(j)
        used.add(i)
        if len(cluster) >= 2:
            avg_price = np.mean([x["price"] for x in cluster])
            zones.append({
                "price": round(avg_price, 5),
                "type": cluster[0]["type"],
                "strength": len(cluster),
            })

    return sorted(zones, key=lambda x: x["price"])


def add_sr_features(df: pd.DataFrame, lookback_window: int = 50) -> pd.DataFrame:
    """
    Adds Fibonacci retracement levels and S/R proximity flags.
    Fibonacci calculated over the last lookback_window bars.
    """
    res = df.copy()
    res["fib_swing_high"] = df["high_price"].rolling(lookback_window).max()
    res["fib_swing_low"] = df["low_price"].rolling(lookback_window).min()

    for r in FIB_LEVELS:
        col = f"fib_{int(r * 1000)}"
        res[col] = res["fib_swing_high"] - (res["fib_swing_high"] - res["fib_swing_low"]) * r

    # S/R proximity (within 0.2% of any Fibonacci level)
    fib_cols = [f"fib_{int(r * 1000)}" for r in FIB_LEVELS]
    res["near_fib_level"] = res.apply(
        lambda row: any(
            abs(row["close_price"] - row.get(col, np.nan)) / row["close_price"] < 0.002
            for col in fib_cols
            if not np.isnan(row.get(col, np.nan))
        ),
        axis=1,
    )
    return res
