"""
Items 4 + 5 of the 5-part statistical-rigor pass: bootstrap confidence
intervals + Cliff's delta comparing the grid-search winner against
production defaults (item 4), and MCC as an additional reported metric
(item 5).

Item 5 confirms backtest_trades already has everything needed to recompute
alternative metrics without re-running the backtest -- direction,
exit_reason, r_outcome, entry_bar_datetime (see storage/schema_curated.sql).
MCC here is computed as matthews_corrcoef(direction, win) -- predicted
class = signal direction (bullish=1/bearish=0), actual class = outcome
(win=1/loss=0). This is a genuinely non-degenerate use of MCC (unlike
naively trying to MCC a single win/loss sequence against a constant
"always predicted win," which is undefined -- denominator zero): it
answers a real, previously-flagged question for this project specifically
-- whether the edge is symmetric across both directions or concentrated in
one (relevant given gold's one-directional bull-run regime, already
flagged as a caveat in every backtest report so far).

MCC and Cliff's delta implemented directly (no scipy/sklearn dependency
needed for either -- both are simple closed-form calculations here).

Exploratory only -- reads raw tables, writes nothing back.

Usage:
    python scripts/backtest/bootstrap_ci_and_mcc.py --symbol XAUUSD --mode choch_only
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

N_BOOTSTRAP = 2000
GRID_CSV = {
    ("XAUUSD", "choch_only"): "docs/optimization_results/20260817_111916_XAUUSD_choch_only_grid.csv",
    ("XAUUSD", "choch_sweep"): "docs/optimization_results/20260817_112645_XAUUSD_choch_sweep_grid.csv",
    ("EURUSD", "choch_only"): "docs/optimization_results/20260817_113701_EURUSD_choch_only_grid.csv",
    ("EURUSD", "choch_sweep"): "docs/optimization_results/20260817_114512_EURUSD_choch_sweep_grid.csv",
}
TRAIN_FLOOR, VAL_FLOOR = 66, 22


def find_winner(report: pd.DataFrame) -> pd.Series:
    train_ok = report[report["train_n"] >= TRAIN_FLOOR].sort_values("train_expectancy", ascending=False)
    top5 = train_ok.head(5)
    top5_val_ok = top5[top5["val_n"] >= VAL_FLOOR]
    if top5_val_ok.empty:
        return top5.iloc[0]
    return top5_val_ok.sort_values("val_expectancy", ascending=False).iloc[0]


def bootstrap_ci(r: np.ndarray, n_boot=N_BOOTSTRAP, seed=0):
    rng = np.random.default_rng(seed)
    n = len(r)
    exp_samples = np.empty(n_boot)
    wr_samples = np.empty(n_boot)
    for i in range(n_boot):
        sample = r[rng.integers(0, n, size=n)]
        exp_samples[i] = sample.mean()
        wr_samples[i] = (sample > 0).mean()
    return {
        "expectancy_ci": (np.percentile(exp_samples, 2.5), np.percentile(exp_samples, 97.5)),
        "winrate_ci": (np.percentile(wr_samples, 2.5), np.percentile(wr_samples, 97.5)),
        "exp_samples": exp_samples,
    }


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """(#a>b - #a<b) / (len(a)*len(b)), computed via rank/sort in O(n log n)
    instead of the naive O(n*m) pairwise comparison."""
    all_vals = np.concatenate([a, b])
    order = np.argsort(all_vals)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(all_vals) + 1)
    # handle ties with average rank
    sorted_vals = all_vals[order]
    i = 0
    while i < len(sorted_vals):
        j = i
        while j + 1 < len(sorted_vals) and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        if j > i:
            avg = ranks[order[i:j + 1]].mean()
            ranks[order[i:j + 1]] = avg
        i = j + 1
    ra = ranks[:len(a)]
    n1, n2 = len(a), len(b)
    u = ra.sum() - n1 * (n1 + 1) / 2.0
    delta = (2 * u) / (n1 * n2) - 1
    return delta


def mcc(direction_bullish: np.ndarray, win: np.ndarray) -> float:
    """matthews_corrcoef(direction, win) hand-rolled -- predicted class =
    direction is bullish (1/0), actual class = trade won (1/0)."""
    tp = int(((direction_bullish == 1) & (win == 1)).sum())
    tn = int(((direction_bullish == 0) & (win == 0)).sum())
    fp = int(((direction_bullish == 1) & (win == 0)).sum())
    fn = int(((direction_bullish == 0) & (win == 1)).sum())
    denom = np.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denom == 0:
        return float("nan")
    return (tp * tn - fp * fn) / denom


def get_trades(symbol, mode, params):
    ltf_tf = "m15"
    m15 = load_bars_in_window(symbol, ltf_tf)
    m5 = load_bars_in_window(symbol, "m5")
    zones = load_zones_raw(symbol)
    zones["created_at_bar"] = pd.to_datetime(zones["created_at_bar"])
    atr_by_h1_bar = load_h1_atr(symbol)

    eng = LTFTriggerEngine(confirmation_window_bars=int(params["confirm_window"]))
    trig = eng.compute_triggers(m15, zones, symbol=symbol, ltf_timeframe=ltf_tf, mode=mode)
    trig["confirmed_at_bar"] = pd.to_datetime(trig["confirmed_at_bar"])
    distinct_bars = pd.Series(trig["confirmed_at_bar"].unique())
    entry_by_bar = load_entry_prices(symbol, ltf_tf, distinct_bars)
    trig["entry_price"] = trig["confirmed_at_bar"].map(entry_by_bar)
    trig["atr_14"] = trig["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)
    trig = trig.reset_index(drop=True)
    trig["id"] = trig.index

    targets = compute_structural_targets(
        trig, zones, fraction=float(params["fraction"]),
        min_risk_atr_multiple=float(params["min_risk"]), max_stop_atr_multiple=float(params["max_stop"]),
    )
    structural = targets[targets["target_status"] == "structural"].copy().reset_index(drop=True)
    structural["id"] = structural.index
    trades, _ = simulate(structural, m15, m5)
    return trades[trades["exit_reason"].isin(["win", "loss"])].copy()


def run_one(symbol: str, mode: str):
    report = pd.read_csv(GRID_CSV[(symbol, mode)])
    winner = find_winner(report)
    defaults = dict(fraction=STRUCTURAL_TP_FRACTION, min_risk=MIN_RISK_ATR_MULTIPLE,
                     max_stop=MAX_STOP_ATR_MULTIPLE, confirm_window=CONFIRMATION_WINDOW_BARS)
    winner_params = dict(fraction=winner["fraction"], min_risk=winner["min_risk"],
                          max_stop=winner["max_stop"], confirm_window=winner["confirm_window"])

    print(f"\n=== {symbol} / {mode} ===")
    print(f"defaults: {defaults}")
    print(f"winner:   {winner_params}")

    default_trades = get_trades(symbol, mode, defaults)
    winner_trades = get_trades(symbol, mode, winner_params) if winner_params != defaults else default_trades

    default_r = default_trades["r_outcome"].astype(float).values
    winner_r = winner_trades["r_outcome"].astype(float).values

    default_tm = trade_metrics(default_r)
    winner_tm = trade_metrics(winner_r)

    default_ci = bootstrap_ci(default_r)
    winner_ci = bootstrap_ci(winner_r)

    delta = cliffs_delta(winner_r, default_r)

    default_dir = (default_trades["direction"] == "bullish").astype(int).values
    default_win = (default_trades["exit_reason"] == "win").astype(int).values
    default_mcc = mcc(default_dir, default_win)

    winner_dir = (winner_trades["direction"] == "bullish").astype(int).values
    winner_win = (winner_trades["exit_reason"] == "win").astype(int).values
    winner_mcc = mcc(winner_dir, winner_win)

    print(f"\ndefaults: n={default_tm['n_trades']}  expectancy={default_tm['expectancy_r']:.4f}R  "
          f"95% CI=[{default_ci['expectancy_ci'][0]:.4f}, {default_ci['expectancy_ci'][1]:.4f}]  "
          f"win_rate={default_tm['win_rate']:.4f} CI=[{default_ci['winrate_ci'][0]:.4f}, {default_ci['winrate_ci'][1]:.4f}]  "
          f"MCC(direction,win)={default_mcc:.4f}")
    print(f"winner:   n={winner_tm['n_trades']}  expectancy={winner_tm['expectancy_r']:.4f}R  "
          f"95% CI=[{winner_ci['expectancy_ci'][0]:.4f}, {winner_ci['expectancy_ci'][1]:.4f}]  "
          f"win_rate={winner_tm['win_rate']:.4f} CI=[{winner_ci['winrate_ci'][0]:.4f}, {winner_ci['winrate_ci'][1]:.4f}]  "
          f"MCC(direction,win)={winner_mcc:.4f}")
    ci_overlap = not (winner_ci['expectancy_ci'][0] > default_ci['expectancy_ci'][1] or
                       default_ci['expectancy_ci'][0] > winner_ci['expectancy_ci'][1])
    print(f"Cliff's delta (winner vs defaults, r_outcome): {delta:.4f}  "
          f"({'negligible' if abs(delta) < 0.147 else 'small' if abs(delta) < 0.33 else 'medium' if abs(delta) < 0.474 else 'large'})")
    print(f"expectancy 95% CIs overlap: {ci_overlap}")

    return dict(symbol=symbol, mode=mode, default_expectancy=default_tm['expectancy_r'], default_ci=default_ci['expectancy_ci'],
                winner_expectancy=winner_tm['expectancy_r'], winner_ci=winner_ci['expectancy_ci'],
                cliffs_delta=delta, ci_overlap=ci_overlap, default_mcc=default_mcc, winner_mcc=winner_mcc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=["XAUUSD", "EURUSD"])
    parser.add_argument("--mode", default="choch_only", choices=list(MODES))
    args = parser.parse_args()
    run_one(args.symbol, args.mode)


if __name__ == "__main__":
    main()
