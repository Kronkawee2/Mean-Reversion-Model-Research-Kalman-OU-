"""
Gold Layer: Vectorized Backtester.

Evaluates historical signals (from MTFStrategyEngine) against OHLCV data.
Metrics: Win Rate, Profit Factor, Max Drawdown, Sharpe Ratio, Equity Curve.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BacktestResult:
    symbol:          str
    tf_exec:         str
    total_signals:   int    = 0
    wins:            int    = 0
    losses:          int    = 0
    pending:         int    = 0
    win_rate:        float  = 0.0
    gross_profit:    float  = 0.0
    gross_loss:      float  = 0.0
    profit_factor:   float  = 0.0
    net_pnl:         float  = 0.0
    avg_win:         float  = 0.0
    avg_loss:        float  = 0.0
    avg_rr_actual:   float  = 0.0
    max_drawdown:    float  = 0.0
    max_drawdown_pct:float  = 0.0
    sharpe_ratio:    float  = 0.0
    equity_curve:    list   = field(default_factory=list)
    closed_signals:  list   = field(default_factory=list)


class Backtester:
    """
    Vectorized backtester for MTFStrategy signals.
    Uses bar-by-bar simulation to determine first-hit exit (TP or SL).
    """

    def __init__(self, max_bars_hold: int = 200):
        """
        max_bars_hold: max candles to hold a trade before forced close at close price.
        """
        self.max_bars_hold = max_bars_hold

    def _evaluate_signal(
        self,
        sig: dict,
        df: pd.DataFrame,
    ) -> dict:
        """
        Simulate a single trade forward bar-by-bar.
        Returns updated signal dict with status, pnl_pts, closed_at, bars_held.
        """
        formed = pd.to_datetime(sig["formed_at"])
        future = df[df["price_datetime"] > formed].head(self.max_bars_hold)

        if future.empty:
            sig["status"]    = "PENDING"
            sig["pnl_pts"]   = None
            sig["closed_at"] = None
            sig["bars_held"] = None
            return sig

        direction = sig["direction"]
        entry     = float(sig["entry"])
        tp        = float(sig["take_profit"])
        sl        = float(sig["stop_loss"])

        for bars_held, (_, row) in enumerate(future.iterrows(), 1):
            h = float(row["high_price"])
            l = float(row["low_price"])

            if direction == "bullish":
                if h >= tp:
                    sig["status"]    = "WIN"
                    sig["pnl_pts"]   = round(tp - entry, 5)
                    sig["closed_at"] = str(row["price_datetime"])[:16]
                    sig["bars_held"] = bars_held
                    return sig
                if l <= sl:
                    sig["status"]    = "LOSS"
                    sig["pnl_pts"]   = round(sl - entry, 5)
                    sig["closed_at"] = str(row["price_datetime"])[:16]
                    sig["bars_held"] = bars_held
                    return sig
            else:
                if l <= tp:
                    sig["status"]    = "WIN"
                    sig["pnl_pts"]   = round(entry - tp, 5)
                    sig["closed_at"] = str(row["price_datetime"])[:16]
                    sig["bars_held"] = bars_held
                    return sig
                if h >= sl:
                    sig["status"]    = "LOSS"
                    sig["pnl_pts"]   = round(entry - sl, 5)
                    sig["closed_at"] = str(row["price_datetime"])[:16]
                    sig["bars_held"] = bars_held
                    return sig

        # Time-out: close at last close price
        last_close = float(future.iloc[-1]["close_price"])
        if direction == "bullish":
            pnl = round(last_close - entry, 5)
        else:
            pnl = round(entry - last_close, 5)

        sig["status"]    = "WIN" if pnl >= 0 else "LOSS"
        sig["pnl_pts"]   = pnl
        sig["closed_at"] = str(future.iloc[-1]["price_datetime"])[:16]
        sig["bars_held"] = self.max_bars_hold
        return sig

    def run(
        self,
        signals_df: pd.DataFrame,
        df_price:   pd.DataFrame,
    ) -> BacktestResult:
        """
        Run backtest on all signals.

        signals_df : output from MTFStrategyEngine.generate_signals()
        df_price   : raw OHLCV DataFrame (same asset/TF as signals)
        """
        if signals_df.empty:
            symbol  = "UNKNOWN"
            tf_exec = "?"
        else:
            symbol  = signals_df["symbol"].iloc[0]
            tf_exec = signals_df["tf_exec"].iloc[0]

        result = BacktestResult(symbol=symbol, tf_exec=tf_exec)
        result.total_signals = len(signals_df)

        closed  = []
        equity  = 0.0
        eq_pts  = []
        peak    = 0.0
        max_dd  = 0.0

        for _, row in signals_df.iterrows():
            sig = row.to_dict()
            sig = self._evaluate_signal(sig, df_price)
            closed.append(sig)

            if sig["status"] in ("WIN", "LOSS") and sig["pnl_pts"] is not None:
                equity += float(sig["pnl_pts"])
                eq_pts.append({"date": sig["closed_at"], "equity": round(equity, 5)})
                peak  = max(peak, equity)
                dd    = peak - equity
                max_dd = max(max_dd, dd)

        wins   = [s for s in closed if s["status"] == "WIN"]
        losses = [s for s in closed if s["status"] == "LOSS"]

        result.wins    = len(wins)
        result.losses  = len(losses)
        result.pending = len([s for s in closed if s["status"] == "PENDING"])

        if wins or losses:
            result.win_rate     = result.wins / (result.wins + result.losses)
            result.gross_profit = sum(float(s["pnl_pts"]) for s in wins)
            result.gross_loss   = abs(sum(float(s["pnl_pts"]) for s in losses))
            result.profit_factor= (result.gross_profit / result.gross_loss) if result.gross_loss else float("inf")
            result.net_pnl      = result.gross_profit - result.gross_loss
            result.avg_win      = result.gross_profit / len(wins)   if wins   else 0
            result.avg_loss     = result.gross_loss   / len(losses) if losses else 0

            rr_vals = []
            for s in wins + losses:
                risk = abs(float(s["entry"]) - float(s["stop_loss"]))
                rewd = abs(float(s["entry"]) - float(s["take_profit"]))
                if risk > 0:
                    rr_vals.append(rewd / risk)
            result.avg_rr_actual = np.mean(rr_vals) if rr_vals else 0.0

            result.max_drawdown = max_dd
            if peak > 0:
                result.max_drawdown_pct = max_dd / peak

            pnl_series = [float(s["pnl_pts"]) for s in wins + losses if s.get("pnl_pts") is not None]
            if len(pnl_series) > 1:
                result.sharpe_ratio = (np.mean(pnl_series) / np.std(pnl_series)) * np.sqrt(252)

        result.equity_curve   = eq_pts
        result.closed_signals = closed
        return result

    def to_dataframe(self, result: BacktestResult) -> pd.DataFrame:
        """Convert BacktestResult.closed_signals to a tidy DataFrame."""
        return pd.DataFrame(result.closed_signals)

    def summary(self, result: BacktestResult) -> dict:
        """Return a flat summary dict for display."""
        return {
            "Symbol":        result.symbol,
            "TF":            result.tf_exec,
            "Total Signals": result.total_signals,
            "Wins":          result.wins,
            "Losses":        result.losses,
            "Pending":       result.pending,
            "Win Rate":      f"{result.win_rate*100:.1f}%",
            "Net PnL pts":   f"{result.net_pnl:+.2f}",
            "Profit Factor": f"{min(result.profit_factor, 99.9):.2f}",
            "Avg Win":       f"{result.avg_win:.2f}",
            "Avg Loss":      f"{result.avg_loss:.2f}",
            "Avg R:R":       f"1:{result.avg_rr_actual:.2f}",
            "Max Drawdown":  f"{result.max_drawdown:.2f} pts ({result.max_drawdown_pct*100:.1f}%)",
            "Sharpe Ratio":  f"{result.sharpe_ratio:.2f}",
        }
