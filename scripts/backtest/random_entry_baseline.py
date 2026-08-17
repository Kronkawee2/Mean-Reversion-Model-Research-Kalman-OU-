"""
Random-entry baseline: same design family as negative_control_temporal_shift.py
(preserve real triggers' direction and $ risk/reward sizing, break the
temporal link to the real structural moment), but instead of one fixed -12h
shift, each real trigger gets re-anchored to an INDEPENDENT UNIFORM RANDOM
timestamp within the same shared window. Run N_DRAWS times (different
random seeds) to get a distribution of "no genuine signal" expectancy,
rather than a single point estimate -- the real signal should sit clearly
above that distribution, not just above one arbitrary draw of it, for the
system to have genuine information content beyond generic favorable drift.

Exploratory only -- reads raw tables, writes nothing back.

Usage:
    python scripts/backtest/random_entry_baseline.py --symbol XAUUSD --mode choch_only
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.detection.run_ltf_trigger_detection import load_htf_zones as load_zones_raw  # noqa: E402
from scripts.backtest.compare_structural_tp_variants import load_h1_atr, load_entry_prices  # noqa: E402
from scripts.backtest.grid_search_structural_tp import load_bars_in_window  # noqa: E402
from analysis.strategies.ltf_trigger_engine import LTFTriggerEngine, MODES, CONFIRMATION_WINDOW_BARS  # noqa: E402
from analysis.strategies.structural_tp_engine import (  # noqa: E402
    compute_structural_targets, STRUCTURAL_TP_FRACTION, MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE,
)
from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics  # noqa: E402

N_DRAWS = 10


def build_random_triggers(real: pd.DataFrame, m15: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Same direction + same $ risk/reward per row as `real`, but entry
    re-anchored to an independently-drawn random m15 bar (with replacement
    across rows -- frequency/long-short mix is preserved by construction
    since we start from a copy of `real`)."""
    candidate_times = m15["price_datetime"].values
    n = len(real)
    picks = rng.choice(len(candidate_times), size=n, replace=True)
    new_times = pd.to_datetime(candidate_times[picks])

    rnd = real.copy()
    rnd["confirmed_at_bar"] = new_times
    price_by_time = m15.set_index("price_datetime")["close_price"]
    rnd["entry_price"] = price_by_time.reindex(new_times).values

    risk = np.where(real["direction"] == "bullish",
                     real["entry_price"] - real["stop_price"],
                     real["stop_price"] - real["entry_price"])
    reward = np.where(real["direction"] == "bullish",
                       real["target_price"] - real["entry_price"],
                       real["entry_price"] - real["target_price"])

    rnd["stop_price"] = np.where(rnd["direction"] == "bullish",
                                  rnd["entry_price"] - risk, rnd["entry_price"] + risk)
    rnd["target_price"] = np.where(rnd["direction"] == "bullish",
                                    rnd["entry_price"] + reward, rnd["entry_price"] - reward)
    rnd["structural_rr"] = reward / risk
    rnd = rnd.dropna(subset=["entry_price"]).reset_index(drop=True)
    rnd["id"] = rnd.index
    return rnd


def run_one(symbol: str, mode: str):
    ltf_tf = "m15"
    m15 = load_bars_in_window(symbol, ltf_tf)
    m5 = load_bars_in_window(symbol, "m5")
    zones = load_zones_raw(symbol)
    zones["created_at_bar"] = pd.to_datetime(zones["created_at_bar"])
    atr_by_h1_bar = load_h1_atr(symbol)

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

    draw_expectancies, draw_winrates = [], []
    for seed in range(N_DRAWS):
        rng = np.random.default_rng(seed)
        rnd_structural = build_random_triggers(real_structural, m15, rng)
        rnd_trades, _ = simulate(rnd_structural, m15, m5)
        rnd_decided = rnd_trades[rnd_trades["exit_reason"].isin(["win", "loss"])]
        rnd_tm = trade_metrics(rnd_decided["r_outcome"].astype(float).values)
        draw_expectancies.append(rnd_tm["expectancy_r"])
        draw_winrates.append(rnd_tm["win_rate"])

    draw_expectancies = np.array(draw_expectancies, dtype=float)
    draw_winrates = np.array(draw_winrates, dtype=float)
    mean_exp, std_exp = draw_expectancies.mean(), draw_expectancies.std(ddof=1)
    z = (real_tm["expectancy_r"] - mean_exp) / std_exp if std_exp > 0 else float("inf")

    print(f"\n=== {symbol} / {mode} ===")
    print(f"real:        n={real_tm['n_trades']}  win_rate={real_tm['win_rate']:.4f}  expectancy={real_tm['expectancy_r']:.4f}R")
    print(f"random ({N_DRAWS} draws): mean_expectancy={mean_exp:.4f}R  std={std_exp:.4f}  "
          f"mean_win_rate={draw_winrates.mean():.4f}  range=[{draw_expectancies.min():.4f}, {draw_expectancies.max():.4f}]")
    print(f"real vs random z-score: {z:.2f}  (real exceeds every one of {N_DRAWS} random draws: {bool((draw_expectancies < real_tm['expectancy_r']).all())})")
    return dict(symbol=symbol, mode=mode, real_expectancy=real_tm['expectancy_r'], real_winrate=real_tm['win_rate'],
                random_mean=mean_exp, random_std=std_exp, z=z)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=["XAUUSD", "EURUSD"])
    parser.add_argument("--mode", default="choch_only", choices=list(MODES))
    args = parser.parse_args()
    run_one(args.symbol, args.mode)


if __name__ == "__main__":
    main()
