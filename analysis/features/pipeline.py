"""
Master Quantitative Feature Pipeline.
Integrates Price/Return, Volatility, Correlation/Spread, Macro, COT Positioning,
and Divergence features into a clean, leakage-free Pandas DataFrame.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional

from .price_return import PriceReturnFeatures
from .volatility import VolatilityFeatures
from .correlation_beta import CorrelationBetaFeatures
from .macro import MacroFeatures
from .positioning import PositioningFeatures


class QuantFeaturePipeline:
    """Master Quantitative Feature Pipeline for XAU/USD and EUR/USD."""

    def __init__(self, asset_name: str = "gold"):
        self.asset_name = asset_name.lower()
        self.pr_feat = PriceReturnFeatures()
        self.vol_feat = VolatilityFeatures()
        self.cb_feat = CorrelationBetaFeatures()
        self.macro_feat = MacroFeatures()
        self.pos_feat = PositioningFeatures()

    def transform(
        self,
        df_asset: pd.DataFrame,
        df_drivers: Optional[Dict[str, pd.DataFrame]] = None,
        df_cot: Optional[pd.DataFrame] = None
    ) -> pd.DataFrame:
        """
        Executes full quantitative feature engineering pipeline.

        Parameters
        ----------
        df_asset : pd.DataFrame
            Primary asset OHLCV dataframe.
        df_drivers : Optional[Dict[str, pd.DataFrame]]
            Dict of driver dataframes (dxy, us10y, vix, gdx, silver).
        df_cot : Optional[pd.DataFrame]
            Weekly CFTC COT report dataframe.

        Returns
        -------
        pd.DataFrame
            DataFrame with all 7 feature categories attached.
        """
        if df_asset.empty:
            return df_asset

        res = df_asset.copy()
        df_drivers = df_drivers or {}

        # 1. Price & Return Features
        res["feat_log_return"] = self.pr_feat.calc_log_return(res["close_price"])
        res["feat_price_ema_dist_z"] = self.pr_feat.calc_price_ema_dist_zscore(res["close_price"])
        res["feat_log_return_slope"] = self.pr_feat.calc_log_return_slope(res["close_price"])

        # 2. Volatility Features
        res["feat_garman_klass_vol"] = self.vol_feat.calc_garman_klass_vol(res)
        res["feat_parkinson_vol"] = self.vol_feat.calc_parkinson_vol(res)
        res["feat_atr_pct"] = self.vol_feat.calc_normalized_atr_pct(res)
        res["feat_volatility_ratio"] = self.vol_feat.calc_volatility_ratio(res["feat_log_return"])

        # 3. Macro Driver Alignments & Features
        if "dxy" in df_drivers and not df_drivers["dxy"].empty:
            dxy_clean = df_drivers["dxy"].sort_values("price_datetime")[["price_datetime", "close_price"]].rename(columns={"close_price": "dxy_close"})
            res = pd.merge_asof(res.sort_values("price_datetime"), dxy_clean, on="price_datetime", direction="backward")
            res["feat_dxy_return_z"] = self.macro_feat.calc_dxy_return_zscore(res["dxy_close"])
            res["feat_dxy_spread_z"] = self.cb_feat.calc_spread_zscore(res["close_price"], res["dxy_close"])
            res["feat_dxy_correlation"] = self.cb_feat.calc_rolling_correlation(res["close_price"], res["dxy_close"])

        if "us10y" in df_drivers and not df_drivers["us10y"].empty:
            u_clean = df_drivers["us10y"].sort_values("price_datetime")[["price_datetime", "close_price"]].rename(columns={"close_price": "us10y_close"})
            res = pd.merge_asof(res.sort_values("price_datetime"), u_clean, on="price_datetime", direction="backward")
            if "dxy_close" in res.columns:
                res["feat_real_yield_proxy"] = self.macro_feat.calc_real_yield_proxy(res["us10y_close"], res["dxy_close"])

        if "vix" in df_drivers and not df_drivers["vix"].empty:
            v_clean = df_drivers["vix"].sort_values("price_datetime")[["price_datetime", "close_price"]].rename(columns={"close_price": "vix_close"})
            res = pd.merge_asof(res.sort_values("price_datetime"), v_clean, on="price_datetime", direction="backward")
            res["feat_vix_regime_flag"] = self.macro_feat.calc_vix_regime_flag(res["vix_close"])
        else:
            res["feat_vix_regime_flag"] = 0.0

        # 4. Asset-Specific Features (Gold vs GDX / Silver Ratio)
        if self.asset_name in ["gold", "xauusd"]:
            if "gdx" in df_drivers and not df_drivers["gdx"].empty:
                gdx_clean = df_drivers["gdx"].sort_values("price_datetime")[["price_datetime", "close_price"]].rename(columns={"close_price": "gdx_close"})
                res = pd.merge_asof(res.sort_values("price_datetime"), gdx_clean, on="price_datetime", direction="backward")
                res["feat_gdx_gold_residual"] = self.macro_feat.calc_gdx_gold_residual(res["close_price"], res["gdx_close"])

            if "silver" in df_drivers and not df_drivers["silver"].empty:
                si_clean = df_drivers["silver"].sort_values("price_datetime")[["price_datetime", "close_price"]].rename(columns={"close_price": "silver_close"})
                res = pd.merge_asof(res.sort_values("price_datetime"), si_clean, on="price_datetime", direction="backward")
                res["feat_gsr_zscore"] = self.cb_feat.calc_gold_silver_ratio_zscore(res["close_price"], res["silver_close"])

        # 5. Positioning Features (CFTC COT)
        if df_cot is not None and not df_cot.empty:
            cot_clean = df_cot.sort_values("report_date").rename(columns={"report_date": "price_datetime"})
            res = pd.merge_asof(res.sort_values("price_datetime"), cot_clean, on="price_datetime", direction="backward")
            if "comm_net_pos" in res.columns:
                res["feat_cot_percentile"] = self.pos_feat.calc_cot_percentile_rank(res["comm_net_pos"])
                res["feat_cot_zscore"] = self.pos_feat.calc_cot_zscore(res["comm_net_pos"])
                res["feat_cot_delta_4w"] = self.pos_feat.calc_cot_delta_4w(res["comm_net_pos"])

        # 6. Integrated Composite Score
        score = pd.Series(index=res.index, data=0.0)

        if "feat_price_ema_dist_z" in res.columns:
            score -= res["feat_price_ema_dist_z"] * 15.0  # Mean reversion weight

        if "feat_dxy_spread_z" in res.columns:
            score -= res["feat_dxy_spread_z"] * 25.0       # Spread Z-score weight

        if "feat_cot_percentile" in res.columns:
            score += (res["feat_cot_percentile"] - 50.0) * 0.5  # Institutional COT weight

        # Apply Volatility Crisis Penalty
        score = np.where(res["feat_vix_regime_flag"] == 1.0, score * 0.5, score)

        res["composite_quant_score"] = np.clip(score, -100.0, 100.0)
        return res
