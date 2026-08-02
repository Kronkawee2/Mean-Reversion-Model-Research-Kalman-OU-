"""
SMC Scoring, Confirmation Filters, and Strategy Blueprint Engine.

SOURCES & OFFICIAL REFERENCES:
- ACY Securities OB + FVG + Liquidity Sweep Confirmation Model: https://acy.com/en/market-news/education/confirmation-model-ob-fvg-liquidity-sweep-j-o-20251112-094218/
- CFTC & CME Macro Inter-Market Confluence Framework
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional

from .structure import SMCStructureEngine
from .liquidity import SMCLiquidityEngine
from .imbalance import SMCImbalanceEngine
from .order_block import SMCOrderBlockEngine
from .crt_engine import CRTEngine


class SMCScoringEngine:
    """Compiles multi-layer SMC & CRT signals into a unified composite score and trade blueprint."""

    def __init__(self, pivot_window: int = 3):
        self.struct_engine = SMCStructureEngine(pivot_window=pivot_window)
        self.liq_engine = SMCLiquidityEngine()
        self.imb_engine = SMCImbalanceEngine()
        self.ob_engine = SMCOrderBlockEngine()
        self.crt_engine = CRTEngine()

    def generate_strategy_blueprint(
        self,
        df_asset: pd.DataFrame,
        df_drivers: Optional[Dict[str, pd.DataFrame]] = None
    ) -> pd.DataFrame:
        """
        Executes full SMC/CRT strategy blueprint pipeline:
        Structure -> Liquidity -> Imbalance -> OB -> CRT -> Scoring.
        """
        if df_asset.empty:
            return df_asset

        df_drivers = df_drivers or {}

        # 1. Pipeline Transformations
        res = self.struct_engine.detect_bos_choch(df_asset)
        res = self.liq_engine.detect_liquidity_sweeps(res)
        res = self.imb_engine.detect_fvg(res)
        res = self.ob_engine.detect_order_blocks(res)
        res = self.crt_engine.detect_session_sweeps(res)
        res = self.crt_engine.calc_premium_discount_equilibrium(res)

        # 2. Macro Driver Alignment (DXY & VIX)
        if "dxy" in df_drivers and not df_drivers["dxy"].empty:
            dxy_clean = df_drivers["dxy"].sort_values("price_datetime")[["price_datetime", "close_price"]].rename(columns={"close_price": "dxy_close"})
            res = pd.merge_asof(res.sort_values("price_datetime"), dxy_clean, on="price_datetime", direction="backward")

        if "vix" in df_drivers and not df_drivers["vix"].empty:
            vix_clean = df_drivers["vix"].sort_values("price_datetime")[["price_datetime", "close_price"]].rename(columns={"close_price": "vix_close"})
            res = pd.merge_asof(res.sort_values("price_datetime"), vix_clean, on="price_datetime", direction="backward")

        # 3. Calculate Composite Scores
        score = pd.Series(index=res.index, data=0.0)

        # Structure Signals
        sig = res.get("smc_structure_signal", pd.Series([None] * len(res)))
        score = np.where(sig == "BULLISH_CHOCH", score + 40, score)
        score = np.where(sig == "BULLISH_BOS", score + 30, score)
        score = np.where(sig == "BEARISH_CHOCH", score - 40, score)
        score = np.where(sig == "BEARISH_BOS", score - 30, score)

        # Liquidity Sweeps
        sweep = res.get("smc_liquidity_sweep", pd.Series([None] * len(res)))
        score = np.where(sweep == "SSL_SWEEP_BULLISH", score + 35, score)
        score = np.where(sweep == "BSL_SWEEP_BEARISH", score - 35, score)

        # FVG Imbalance
        fvg = res.get("smc_fvg_type", pd.Series([None] * len(res)))
        mitigated_fvg = res.get("smc_fvg_mitigated", pd.Series([False] * len(res)))
        score = np.where((fvg == "BULLISH_FVG") & (~mitigated_fvg), score + 20, score)
        score = np.where((fvg == "BEARISH_FVG") & (~mitigated_fvg), score - 20, score)

        # Premium / Discount Zone Filter
        zone = res.get("smc_zone", pd.Series(["NEUTRAL"] * len(res)))
        score = np.where((score > 0) & (zone == "DISCOUNT"), score + 15, score)
        score = np.where((score < 0) & (zone == "PREMIUM"), score - 15, score)

        # VIX Volatility Penalty
        if "vix_close" in res.columns:
            score = np.where(res["vix_close"] > 25.0, score * 0.5, score)

        res["composite_smc_score"] = np.clip(score, -100.0, 100.0)

        # Signal Action
        res["smc_action"] = "HOLD"
        res["smc_action"] = np.where(res["composite_smc_score"] >= 50.0, "BUY", res["smc_action"])
        res["smc_action"] = np.where(res["composite_smc_score"] <= -50.0, "SELL", res["smc_action"])

        return res
