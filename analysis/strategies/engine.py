"""
Gold Layer: MTF Strategy Engine.

Execution timeframe: 5m / 15m (entry trigger)
Bias filter: 1h / 4h / 1d (trend direction must align)

Entry condition: Confluence score >= min_conf (default 4/7) on exec TF
  AND higher-TF trend bias agrees with direction.

Exit: ATR-based SL (1.5x ATR14) + TP (R:R 1:2 default)
"""

import numpy as np
import pandas as pd
from typing import Optional
from analysis.smc_crt.scoring        import SMCScoringEngine
from analysis.divergence.signal_generator import DivergenceSignalGenerator
from analysis.technical_analysis      import calc_rsi, calc_atr


class MTFStrategyEngine:
    """
    Multi-Timeframe Strategy: detect confluence signals on exec TF,
    filter by higher-TF bias, output trade records.
    """

    def __init__(
        self,
        min_confluence: int = 4,
        atr_sl_mult:    float = 1.5,
        risk_reward:    float = 2.0,
        pivot_window:   int   = 3,
    ):
        self.min_confluence = min_confluence
        self.atr_sl_mult    = atr_sl_mult
        self.risk_reward    = risk_reward
        self.smc_engine     = SMCScoringEngine(pivot_window=pivot_window)
        self.div_engine     = DivergenceSignalGenerator(pivot_window=pivot_window)

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _safe_str(val) -> Optional[str]:
        """Return str or None — guards against float NaN."""
        if val is None:
            return None
        try:
            if isinstance(val, float) and np.isnan(val):
                return None
        except Exception:
            pass
        return str(val) if val else None

    def _score_bar(self, smc_row, div_row) -> tuple[int, str, list]:
        """
        Score a single bar across 7 confluence conditions.
        Returns (score, direction, conditions_list).
        """
        s    = self._safe_str
        bull = 0
        bear = 0
        hits = []
        score = 0

        # [1] FVG unmitigated nearby
        fvg = s(smc_row.get("smc_fvg_type"))
        if fvg and not bool(smc_row.get("smc_fvg_mitigated")):
            score += 1; hits.append("FVG")
            if "BULLISH" in fvg: bull += 1
            else:                bear += 1

        # [2] Order Block unmitigated nearby
        ob = s(smc_row.get("smc_ob_type"))
        if ob and not bool(smc_row.get("smc_ob_mitigated")):
            score += 1; hits.append("OB")
            if "BULLISH" in ob: bull += 1
            else:               bear += 1

        # [3] Liquidity Sweep
        sweep = s(smc_row.get("smc_liquidity_sweep"))
        if sweep:
            score += 1; hits.append("SWEEP")
            if "SSL" in sweep: bull += 1
            else:              bear += 1

        # [4] RSI Divergence
        rsi_div = s(div_row.get("div_rsi_14_signal")) if div_row is not None else None
        if rsi_div and rsi_div not in ("NONE", "None"):
            score += 1; hits.append(rsi_div[:10])
            if "BULLISH" in rsi_div: bull += 1
            else:                    bear += 1

        # [5] BOS / CHoCH
        struct = s(smc_row.get("smc_structure_signal"))
        if struct:
            score += 1; hits.append(struct[:10])
            if "BULLISH" in struct: bull += 1
            else:                   bear += 1

        # [6] Premium / Discount alignment
        zone = s(smc_row.get("smc_zone")) or "NEUTRAL"
        if zone == "DISCOUNT":
            score += 1; bull += 1; hits.append("DISCOUNT")
        elif zone == "PREMIUM":
            score += 1; bear += 1; hits.append("PREMIUM")

        # [7] VIX macro OK
        vol_ok = bool(div_row.get("volatility_stable", True)) if div_row is not None else True
        if vol_ok:
            score += 1; hits.append("VIX_OK")

        direction = "bullish" if bull > bear else ("bearish" if bear > bull else "NEUTRAL")
        return score, direction, hits

    # ── HTF Bias ─────────────────────────────────────────────────────────────

    def calc_htf_bias(self, df_htf: pd.DataFrame, drivers: dict = None) -> str:
        """
        Compute trend bias from a higher-TF DataFrame.
        Returns 'bullish' | 'bearish' | 'NEUTRAL'.
        """
        if df_htf is None or len(df_htf) < 20:
            return "NEUTRAL"
        drivers = drivers or {}
        smc_htf = self.smc_engine.generate_strategy_blueprint(df_htf, drivers)
        bias    = smc_htf["smc_trend_bias"].iloc[-1] if "smc_trend_bias" in smc_htf.columns else "NEUTRAL"
        return bias.lower() if bias in ("BULLISH", "BEARISH") else "NEUTRAL"

    # ── Main Signal Generation ────────────────────────────────────────────────

    def generate_signals(
        self,
        df_exec: pd.DataFrame,
        drivers: dict = None,
        df_htf:  pd.DataFrame = None,
        symbol:  str = "UNKNOWN",
        tf_exec: str = "5m",
        tf_htf:  str = "1h",
    ) -> pd.DataFrame:
        """
        Run full pipeline on exec TF, filter by HTF bias.
        Returns DataFrame of trade signals.
        """
        drivers = drivers or {}

        # Prepare exec TF
        df = df_exec.copy()
        df["rsi_14"] = calc_rsi(df["close_price"], 14)
        df["atr_14"] = calc_atr(df, 14)

        smc_df = self.smc_engine.generate_strategy_blueprint(df, drivers)
        div_df = self.div_engine.generate_composite_signals(df, drivers)

        # HTF bias filter
        htf_bias = self.calc_htf_bias(df_htf, drivers) if df_htf is not None else "NEUTRAL"

        atr_vals  = calc_atr(df, 14).values
        close_arr = df["close_price"].values
        n = min(len(smc_df), len(div_df), len(df))

        records = []
        for i in range(50, n):
            smc_row = smc_df.iloc[i].to_dict()
            div_row = div_df.iloc[i].to_dict() if i < len(div_df) else None

            score, direction, conds = self._score_bar(smc_row, div_row)

            if score < self.min_confluence:
                continue
            if direction == "NEUTRAL":
                continue

            # HTF alignment check
            if htf_bias != "NEUTRAL" and htf_bias != direction:
                continue

            entry = float(close_arr[i])
            atr_v = float(atr_vals[i]) if not np.isnan(atr_vals[i]) else entry * 0.005

            if direction == "bullish":
                sl = entry - self.atr_sl_mult * atr_v
                tp = entry + self.atr_sl_mult * self.risk_reward * atr_v
            else:
                sl = entry + self.atr_sl_mult * atr_v
                tp = entry - self.atr_sl_mult * self.risk_reward * atr_v

            records.append({
                "symbol":          symbol,
                "tf_exec":         tf_exec,
                "tf_htf":          tf_htf,
                "formed_at":       str(df["price_datetime"].iloc[i])[:16],
                "direction":       direction,
                "entry":           round(entry, 5),
                "stop_loss":       round(sl,    5),
                "take_profit":     round(tp,    5),
                "atr_14":          round(atr_v, 5),
                "confluence_score": score,
                "confluence_max":  7,
                "conditions":      "|".join(conds),
                "htf_bias":        htf_bias,
                "confidence":      round(score / 7, 4),
                "risk_reward":     self.risk_reward,
                "status":          "PENDING",
                "pnl_pts":         None,
                "closed_at":       None,
            })

        return pd.DataFrame(records)
