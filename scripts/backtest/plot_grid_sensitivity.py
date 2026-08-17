"""
Sensitivity + neighbor-stability plots for a grid_search_structural_tp.py
run. Reads the raw per-combination CSV (all 81 rows, every parameter and
every train/val/test metric) that script already writes to
docs/optimization_results/ -- doesn't recompute anything, purely
visualizes what's already there.

Two plot types per symbol/mode:
  1. One-at-a-time sensitivity: for each of the 4 parameters, hold the
     other 3 at the winning combination's values, vary that one parameter
     across its grid values, plot train/val/test expectancy as three
     lines. Makes an overfitting gap (train diverging from val/test) or
     its absence visually obvious rather than only readable from a table.
  2. Neighbor stability: the winning combination plus every grid cell
     exactly one parameter-step away from it (Hamming distance 1 in the
     grid), train/val/test expectancy as grouped bars -- shows whether
     the winner sits on a sharp isolated peak or a broad plateau.

The "winner" is re-derived from the CSV using the exact same selection
rule grid_search_structural_tp.py uses (top-5 train expectancy among
floor-clearing combos, best validation expectancy among those clearing
the validation floor) rather than re-typed from the earlier report, so
there's no transcription risk between the numbers and the plots.

Usage:
    python scripts/backtest/plot_grid_sensitivity.py \\
        docs/optimization_results/20260817_111916_XAUUSD_choch_only_grid.csv \\
        --symbol XAUUSD --mode choch_only --out-dir docs/optimization_results/20260817_sensitivity
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

TRAIN_FLOOR, VAL_FLOOR, TEST_FLOOR = 66, 22, 22
PARAMS = ["fraction", "min_risk", "max_stop", "confirm_window"]
PARAM_LABELS = {
    "fraction": "STRUCTURAL_TP_FRACTION",
    "min_risk": "MIN_RISK_ATR_MULTIPLE",
    "max_stop": "MAX_STOP_ATR_MULTIPLE (stop ATR cap)",
    "confirm_window": "CONFIRMATION_WINDOW_BARS",
}
COLORS = {"train": "#4c72b0", "val": "#dd8452", "test": "#55a868"}


def find_winner(report: pd.DataFrame) -> pd.Series:
    train_ok = report[report["train_n"] >= TRAIN_FLOOR].sort_values("train_expectancy", ascending=False)
    top5 = train_ok.head(5)
    top5_val_ok = top5[top5["val_n"] >= VAL_FLOOR]
    if top5_val_ok.empty:
        return top5.iloc[0]
    return top5_val_ok.sort_values("val_expectancy", ascending=False).iloc[0]


def plot_sensitivity(report: pd.DataFrame, winner: pd.Series, symbol: str, mode: str, out_dir: Path):
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    fig.suptitle(f"{symbol} / {mode} — one-at-a-time parameter sensitivity\n"
                 f"(other 3 params held at winner's values: "
                 f"fraction={winner['fraction']}, min_risk={winner['min_risk']}, "
                 f"max_stop={winner['max_stop']}, confirm_window={int(winner['confirm_window'])})",
                 fontsize=10)

    for ax, param in zip(axes.flat, PARAMS):
        others = [p for p in PARAMS if p != param]
        mask = pd.Series(True, index=report.index)
        for o in others:
            mask &= report[o] == winner[o]
        sub = report[mask].sort_values(param)

        for period in ("train", "val", "test"):
            ax.plot(sub[param], sub[f"{period}_expectancy"], marker="o", label=period,
                     color=COLORS[period], linewidth=2)
        ax.axvline(winner[param], color="gray", linestyle="--", linewidth=1, alpha=0.6)
        ax.set_xlabel(PARAM_LABELS[param], fontsize=9)
        ax.set_ylabel("expectancy (R)", fontsize=9)
        ax.axhline(0, color="black", linewidth=0.5, alpha=0.4)
        ax.grid(alpha=0.3)

    axes.flat[0].legend(fontsize=9, loc="best")
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    path = out_dir / f"{symbol}_{mode}_sensitivity.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def plot_neighbor_stability(report: pd.DataFrame, winner: pd.Series, symbol: str, mode: str, out_dir: Path):
    def hamming(row):
        return sum(row[p] != winner[p] for p in PARAMS)

    dist = report.apply(hamming, axis=1)
    neighbors = report[dist <= 1].copy()
    neighbors["dist"] = dist[dist <= 1]
    neighbors = neighbors.sort_values(["dist"] + PARAMS)
    neighbors["label"] = neighbors.apply(
        lambda r: "WINNER" if r["dist"] == 0 else
        f"{[p for p in PARAMS if r[p] != winner[p]][0]}={r[[p for p in PARAMS if r[p] != winner[p]][0]]}",
        axis=1,
    )

    x = range(len(neighbors))
    width = 0.25
    fig, ax = plt.subplots(figsize=(max(9, len(neighbors) * 0.5), 5.5))
    for i, period in enumerate(("train", "val", "test")):
        ax.bar([xi + (i - 1) * width for xi in x], neighbors[f"{period}_expectancy"],
               width=width, label=period, color=COLORS[period])
    ax.set_xticks(list(x))
    ax.set_xticklabels(neighbors["label"], rotation=45, ha="right", fontsize=8)
    ax.axhline(0, color="black", linewidth=0.5, alpha=0.4)
    ax.set_ylabel("expectancy (R)")
    ax.set_title(f"{symbol} / {mode} — winner vs. one-parameter-step neighbors\n"
                 f"(winner: fraction={winner['fraction']}, min_risk={winner['min_risk']}, "
                 f"max_stop={winner['max_stop']}, confirm_window={int(winner['confirm_window'])})",
                 fontsize=10)
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    path = out_dir / f"{symbol}_{mode}_neighbor_stability.png"
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = pd.read_csv(args.csv_path)
    winner = find_winner(report)
    print(f"{args.symbol}/{args.mode} winner: fraction={winner['fraction']} min_risk={winner['min_risk']} "
          f"max_stop={winner['max_stop']} confirm_window={int(winner['confirm_window'])}  "
          f"train={winner['train_expectancy']:.4f} val={winner['val_expectancy']:.4f} test={winner['test_expectancy']:.4f}")

    p1 = plot_sensitivity(report, winner, args.symbol, args.mode, out_dir)
    p2 = plot_neighbor_stability(report, winner, args.symbol, args.mode, out_dir)
    print(f"Written: {p1}")
    print(f"Written: {p2}")


if __name__ == "__main__":
    main()
