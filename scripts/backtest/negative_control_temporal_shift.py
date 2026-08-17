"""
Negative control: temporal-shift permutation test. Confirmed with the user
as the top-priority check of a 5-part statistical-rigor pass -- if this
comes back positive, it invalidates the rest of today's optimization work
and takes priority over everything else.

Design: take the REAL structural triggers (production defaults:
STRUCTURAL_TP_FRACTION=0.85, MIN_RISK_ATR_MULTIPLE=0.5,
MAX_STOP_ATR_MULTIPLE=1.5, CONFIRMATION_WINDOW_BARS=20) and shift
confirmed_at_bar back by -12h for every trigger. entry_price is re-looked-up
fresh at the shifted timestamp (not reused from the real trigger) --
otherwise the "entry" wouldn't correspond to the shifted moment at all.
stop_price/target_price are recomputed by preserving the REAL trigger's
absolute $ risk and reward distances anchored to the NEW entry price, so
the shifted version has the identical signal frequency, direction
distribution, and R:R shape as the real one -- only WHEN each trade
starts (and therefore which real price path it walks forward through) is
different. This deliberately breaks the real signal-to-outcome
relationship (a shifted "signal" has no structural basis at the shifted
bar) while controlling for everything else that could explain apparent
edge on its own (frequency, R:R sizing, long/short mix).

If shifted expectancy/win rate comes out comparably positive to the real
result, that's evidence the backtest's apparent edge isn't actually tied
to the real trigger moment -- i.e. a lookahead bug or a market-wide
drift/mean-reversion property showing up regardless of signal validity,
not genuine information content in the SMC/CRT trigger itself.

Exploratory only -- reads raw tables directly, writes nothing back.

Usage:
    python scripts/backtest/negative_control_temporal_shift.py --symbol XAUUSD --mode choch_only
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.detection.run_ltf_trigger_detection import load_htf_zones as load_zones_raw  # noqa: E402
from scripts.backtest.compare_structural_tp_variants import load_h1_atr  # noqa: E402
from scripts.backtest.grid_search_structural_tp import load_bars_in_window, WINDOW_START, WINDOW_END  # noqa: E402
from analysis.strategies.ltf_trigger_engine import LTFTriggerEngine, MODES, CONFIRMATION_WINDOW_BARS  # noqa: E402
from analysis.strategies.structural_tp_engine import (  # noqa: E402
    compute_structural_targets, STRUCTURAL_TP_FRACTION, MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE,
)
from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics  # noqa: E402

SHIFT_HOURS = -12


def price_at_or_before(m15: pd.DataFrame, ts: pd.Timestamp):
    """Nearest m15 close at or before ts -- used to re-anchor entry_price
    at the shifted timestamp (m15 bars are the LTF granularity triggers
    are confirmed on)."""
    sub = m15[m15["price_datetime"] <= ts]
    if sub.empty:
        return None
    return float(sub.iloc[-1]["close_price"])


def build_shifted_triggers(real: pd.DataFrame, m15: pd.DataFrame) -> pd.DataFrame:
    shifted = real.copy()
    shifted["confirmed_at_bar"] = shifted["confirmed_at_bar"] + pd.Timedelta(hours=SHIFT_HOURS)

    new_entries = []
    for _, row in shifted.iterrows():
        new_entries.append(price_at_or_before(m15, row["confirmed_at_bar"]))
    shifted["entry_price"] = new_entries
    shifted = shifted.dropna(subset=["entry_price"]).reset_index(drop=True)

    risk = np.where(real["direction"] == "bullish",
                     real["entry_price"] - real["stop_price"],
                     real["stop_price"] - real["entry_price"])
    reward = np.where(real["direction"] == "bullish",
                       real["target_price"] - real["entry_price"],
                       real["entry_price"] - real["target_price"])
    # align risk/reward (computed from the REAL, unshifted rows) back onto
    # the shifted frame by original position, since dropna above may have
    # removed some rows near the start of the window
    risk = pd.Series(risk, index=real.index).loc[shifted.index]
    reward = pd.Series(reward, index=real.index).loc[shifted.index]

    shifted["stop_price"] = np.where(shifted["direction"] == "bullish",
                                      shifted["entry_price"] - risk, shifted["entry_price"] + risk)
    shifted["target_price"] = np.where(shifted["direction"] == "bullish",
                                        shifted["entry_price"] + reward, shifted["entry_price"] - reward)
    shifted["structural_rr"] = reward / risk
    return shifted


def run_one(symbol: str, mode: str):
    ltf_tf = "m15"
    m15 = load_bars_in_window(symbol, ltf_tf)
    m5 = load_bars_in_window(symbol, "m5")
    zones = load_zones_raw(symbol)
    zones["created_at_bar"] = pd.to_datetime(zones["created_at_bar"])
    atr_by_h1_bar = load_h1_atr(symbol)

    from scripts.backtest.compare_structural_tp_variants import load_entry_prices

    eng = LTFTriggerEngine(confirmation_window_bars=CONFIRMATION_WINDOW_BARS)
    trig = eng.compute_triggers(m15, zones, symbol=symbol, ltf_timeframe=ltf_tf, mode=mode)
    trig["confirmed_at_bar"] = pd.to_datetime(trig["confirmed_at_bar"])
    distinct_bars = pd.Series(trig["confirmed_at_bar"].unique())
    entry_by_bar = load_entry_prices(symbol, ltf_tf, distinct_bars)
    trig["entry_price"] = trig["confirmed_at_bar"].map(entry_by_bar)
    trig["atr_14"] = trig["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)
    trig = trig.reset_index(drop=True)
    trig["id"] = trig.index

    targets = compute_structural_targets(
        trig, zones, fraction=STRUCTURAL_TP_FRACTION,
        min_risk_atr_multiple=MIN_RISK_ATR_MULTIPLE, max_stop_atr_multiple=MAX_STOP_ATR_MULTIPLE,
    )
    real_structural = targets[targets["target_status"] == "structural"].copy().reset_index(drop=True)
    real_structural["id"] = real_structural.index

    real_trades, _ = simulate(real_structural, m15, m5)
    real_decided = real_trades[real_trades["exit_reason"].isin(["win", "loss"])]
    real_tm = trade_metrics(real_decided["r_outcome"].astype(float).values)

    shifted_structural = build_shifted_triggers(real_structural, m15)
    shifted_structural["id"] = shifted_structural.index
    shifted_trades, _ = simulate(shifted_structural, m15, m5)
    shifted_decided = shifted_trades[shifted_trades["exit_reason"].isin(["win", "loss"])]
    shifted_tm = trade_metrics(shifted_decided["r_outcome"].astype(float).values)

    print(f"\n=== {symbol} / {mode} ===")
    print(f"real:    n={real_tm['n_trades']}  win_rate={real_tm['win_rate']:.4f}  "
          f"expectancy={real_tm['expectancy_r']:.4f}R  profit_factor={real_tm['profit_factor']}")
    print(f"shifted: n={shifted_tm['n_trades']}  win_rate={shifted_tm['win_rate']:.4f}  "
          f"expectancy={shifted_tm['expectancy_r']:.4f}R  profit_factor={shifted_tm['profit_factor']}")
    gap = real_tm['expectancy_r'] - shifted_tm['expectancy_r']
    print(f"gap (real - shifted): {gap:.4f}R")
    return dict(symbol=symbol, mode=mode, real_n=real_tm['n_trades'], real_winrate=real_tm['win_rate'],
                real_expectancy=real_tm['expectancy_r'], shifted_n=shifted_tm['n_trades'],
                shifted_winrate=shifted_tm['win_rate'], shifted_expectancy=shifted_tm['expectancy_r'], gap=gap)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=["XAUUSD", "EURUSD"])
    parser.add_argument("--mode", default="choch_only", choices=list(MODES))
    args = parser.parse_args()
    run_one(args.symbol, args.mode)


if __name__ == "__main__":
    main()
