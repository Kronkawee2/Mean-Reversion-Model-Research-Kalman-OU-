"""
Signal Generator & Risk Management Engine.

SOURCES & OFFICIAL REFERENCES:
- ATR Volatility-Based Stop-Loss & Take-Profit Boundaries: Wilder's Volatility System (Investopedia / CFI)
- Quantitative Signal Compilation & Scoring: Composite Alpha Model Framework
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from .detection import DivergenceDetector
from .confirmation import DivergenceConfirmationFilter
from .feature_engineering import DivergenceFeatureEngine


class DivergenceSignalGenerator:
    """
    Executes full quantitative pipeline: Feature -> Detect -> Confirm -> Signal -> Risk Management.
    """

    def __init__(self, pivot_window: int = 3):
        self.detector = DivergenceDetector(pivot_window=pivot_window)
        self.filter = DivergenceConfirmationFilter()
        self.feature_engine = DivergenceFeatureEngine()

    def generate_composite_signals(
        self,
        df_asset: pd.DataFrame,
        df_drivers: Optional[Dict[str, pd.DataFrame]] = None,
        atr_multiplier_sl: float = 1.5,
        risk_reward_ratio: float = 2.0
    ) -> pd.DataFrame:
        """
        Runs comprehensive divergence analysis pipeline and outputs composite trading signals.

        RISK MANAGEMENT FORMULAS:
        - Long Stop Loss (SL) = Entry Price - (1.5 * ATR_14)
        - Long Take Profit (TP) = Entry Price + (1.5 * Risk_Reward * ATR_14) -> Default R:R = 1:2
        - Short Stop Loss (SL) = Entry Price + (1.5 * ATR_14)
        - Short Take Profit (TP) = Entry Price - (1.5 * Risk_Reward * ATR_14) -> Default R:R = 1:2
        """
        res = df_asset.copy()
        df_drivers = df_drivers or {}

        # 1. Technical Divergences (RSI) [Ref: CFI & Investopedia]
        if "rsi_14" in res.columns:
            res = self.detector.detect_technical_divergence(res, indicator_col="rsi_14")

        # 2. Inter-market Macro Divergence (DXY) [Ref: CME Group & ICE DXY]
        if "dxy" in df_drivers and not df_drivers["dxy"].empty:
            dxy_clean = df_drivers["dxy"].rename(columns={"close_price": "dxy_close"})
            if "dxy_close" not in res.columns:
                res = pd.merge_asof(
                    res.sort_values("price_datetime"),
                    dxy_clean[["price_datetime", "dxy_close"]].sort_values("price_datetime"),
                    on="price_datetime",
                    direction="backward"
                )
            res = self.detector.detect_intermarket_divergence(
                res, driver_close_col="dxy_close", expected_relationship="inverse"
            )

        # 3. Correlation Stability Check (Asset vs DXY) [Ref: Quant Risk Analysis]
        if "dxy_close" in res.columns:
            res["dxy_corr_valid"] = self.filter.check_correlation_stability(
                res["close_price"], res["dxy_close"], window=60, expected_negative=True
            )
        else:
            res["dxy_corr_valid"] = True

        # 4. Volatility Regime Check (VIX) [Ref: CBOE Volatility Guidelines]
        if "vix" in df_drivers and not df_drivers["vix"].empty:
            vix_clean = df_drivers["vix"].rename(columns={"close_price": "vix_close"})
            if "vix_close" not in res.columns:
                res = pd.merge_asof(
                    res.sort_values("price_datetime"),
                    vix_clean[["price_datetime", "vix_close"]].sort_values("price_datetime"),
                    on="price_datetime",
                    direction="backward"
                )
            res["volatility_stable"] = self.filter.filter_volatility_regime(res, vix_col="vix_close")
        else:
            res["volatility_stable"] = True

        # 5. Calculate Composite Score & Signal Generation
        res["composite_score"] = 0
        res["signal_action"] = "HOLD"
        res["stop_loss_price"] = np.nan
        res["take_profit_price"] = np.nan
        res["position_size_pct"] = 0.0

        n = len(res)
        close = res["close_price"].values
        
        # ATR calculation for Dynamic Risk Limits [Ref: J. Welles Wilder]
        if "atr_14" in res.columns:
            atr = res["atr_14"].values
        else:
            atr = (res["high_price"] - res["low_price"]).rolling(14).mean().fillna(close * 0.01).values

        rsi_div = res.get("div_rsi_14_signal", pd.Series([None] * n)).values
        macro_div = res.get("div_intermarket_dxy", pd.Series([None] * n)).values
        corr_valid = res["dxy_corr_valid"].values
        vol_stable = res["volatility_stable"].values

        for i in range(n):
            score = 0

            # Score Technical Divergences (+40 / -40)
            if rsi_div[i] == "REGULAR_BULLISH":
                score += 40
            elif rsi_div[i] == "HIDDEN_BULLISH":
                score += 25
            elif rsi_div[i] == "REGULAR_BEARISH":
                score -= 40
            elif rsi_div[i] == "HIDDEN_BEARISH":
                score -= 25

            # Score Inter-Market Macro Divergence (+50 / -50)
            if corr_valid[i]:
                if macro_div[i] == "INTERMARKET_BULLISH":
                    score += 50
                elif macro_div[i] == "INTERMARKET_BEARISH":
                    score -= 50

            # Deduct score if high volatility regime (VIX > 25)
            if not vol_stable[i]:
                score = int(score * 0.5)

            res.iloc[i, res.columns.get_loc("composite_score")] = score

            # Generate Signal Actions & ATR Risk Boundaries
            if score >= 50:
                res.iloc[i, res.columns.get_loc("signal_action")] = "BUY"
                sl = close[i] - (atr_multiplier_sl * atr[i])
                tp = close[i] + (atr_multiplier_sl * risk_reward_ratio * atr[i])
                res.iloc[i, res.columns.get_loc("stop_loss_price")] = round(sl, 4)
                res.iloc[i, res.columns.get_loc("take_profit_price")] = round(tp, 4)
                res.iloc[i, res.columns.get_loc("position_size_pct")] = 1.0 if vol_stable[i] else 0.5

            elif score <= -50:
                res.iloc[i, res.columns.get_loc("signal_action")] = "SELL"
                sl = close[i] + (atr_multiplier_sl * atr[i])
                tp = close[i] - (atr_multiplier_sl * risk_reward_ratio * atr[i])
                res.iloc[i, res.columns.get_loc("stop_loss_price")] = round(sl, 4)
                res.iloc[i, res.columns.get_loc("take_profit_price")] = round(tp, 4)
                res.iloc[i, res.columns.get_loc("position_size_pct")] = 1.0 if vol_stable[i] else 0.5

        return res
