"""
3-way (train/validation/test) grid search over STRUCTURAL_TP_FRACTION,
MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE, and CONFIRMATION_WINDOW_BARS
-- a stricter overfitting control than the plain 70/30 train/test split
run_structural_backtest.py uses. Confirmed with the user as an exploratory
search, not a production change: grid search happens on TRAIN only, the
top candidates get evaluated on VALIDATION (iteration allowed here without
touching test), and the single final candidate gets evaluated ONCE on
TEST with no further iteration after that.

Exploratory only -- recomputes everything in memory from the same raw
triggers/zones/entry/ATR data as compare_structural_tp_variants.py, does
NOT write to ltf_trigger_signals/backtest_runs/backtest_trades.

STRICT TIME ALIGNMENT (confirmed with the user, not optional): every
symbol/mode combination run through this script in the same optimization
pass uses the identical WINDOW_START/TRAIN_END/VAL_END/WINDOW_END dates
below, not each symbol's own independently-computed max-available range --
otherwise a symbol with deeper raw history gets an unfair sample-size
advantage over one with shallower history in the comparison. These dates
are hardcoded module constants for exactly that reason (so every
invocation of this script during one optimization round shares them by
construction, not by remembering to pass matching CLI args each time).

WINDOW SIZE, calibrated from real timing data, not guessed: the true
shared window (bounded by EURUSD's shallower M15 broker ceiling,
2022-08-08) is ~4 years, but LTFTriggerEngine.compute_triggers() was
measured to scale as ~O(n^1.82) with bar count (25s at 11,846 bars, 96.2s
at 24,881 bars -- see docs/DECISIONS.md), so the full ~4-year window would
take an estimated 2-4 hours for all 4 symbol/mode combinations. Shrunk to
~200 days instead (~37min estimated for all 4 combinations, confirmed the
statistical floor still clears for EURUSD, the binding symbol, with real
trade counts: train=362/floor=66, val=115/floor=22, test=122/floor=22)
-- a real, reported trade-off against the original ~12-18 month target,
not a silently-picked smaller number.

Usage (run once per symbol/mode with the SAME window constants in effect,
i.e. don't edit WINDOW_START etc. between runs of the same comparison):
    python scripts/backtest/grid_search_structural_tp.py --symbol XAUUSD --mode choch_only
    python scripts/backtest/grid_search_structural_tp.py --symbol XAUUSD --mode choch_sweep
    python scripts/backtest/grid_search_structural_tp.py --symbol EURUSD --mode choch_only
    python scripts/backtest/grid_search_structural_tp.py --symbol EURUSD --mode choch_sweep
"""

import argparse
import itertools
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.detection.run_ltf_trigger_detection import load_ltf_bars, load_htf_zones as load_zones_raw  # noqa: E402
from scripts.backtest.compare_structural_tp_variants import load_raw_bars, load_h1_atr, load_entry_prices  # noqa: E402
from analysis.strategies.ltf_trigger_engine import LTFTriggerEngine, MODES  # noqa: E402
from analysis.strategies.structural_tp_engine import (  # noqa: E402
    compute_structural_targets, STRUCTURAL_TP_FRACTION, MIN_RISK_ATR_MULTIPLE, MAX_STOP_ATR_MULTIPLE,
)
from analysis.strategies.ltf_trigger_engine import CONFIRMATION_WINDOW_BARS  # noqa: E402
from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402
from analysis.backtester.deflated_sharpe import deflated_sharpe_ratio, trade_metrics, sharpe_ratio  # noqa: E402

MIN_TRADES_PER_12_MONTHS = 200

# Strict cross-symbol/cross-mode time alignment (confirmed with the user):
# every symbol/mode combination in a given optimization run uses these SAME
# calendar dates, not its own independently-computed max-available range --
# otherwise a symbol with deeper history gets an unfair sample-size
# advantage in the comparison. Bounded by EURUSD's shallower M15 ceiling
# (2022-08-08), then shrunk further from the full ~4-year shared window to
# ~200 days to fit a real compute-time budget -- see docs/DECISIONS.md for
# the calibrated-scaling reasoning (LTFTriggerEngine.compute_triggers() is
# ~O(n^1.82), not linear, confirmed from real timing at two data sizes).
WINDOW_START = pd.Timestamp("2026-01-27 00:30:43")
WINDOW_END = pd.Timestamp("2026-08-15 00:30:43")
TRAIN_END = pd.Timestamp("2026-05-27 00:30:43")
VAL_END = pd.Timestamp("2026-07-06 00:30:43")

FRACTION_GRID = [0.70, 0.85, 1.00]
MIN_RISK_GRID = [0.3, 0.5, 0.7]
MAX_STOP_GRID = [1.5, 2.0, 2.5]
CONFIRM_WINDOW_GRID = [10, 20, 30]

CURRENT_DEFAULTS = dict(
    fraction=STRUCTURAL_TP_FRACTION,
    min_risk_atr_multiple=MIN_RISK_ATR_MULTIPLE,
    max_stop_atr_multiple=MAX_STOP_ATR_MULTIPLE,
    confirmation_window_bars=CONFIRMATION_WINDOW_BARS,
)


RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}


def load_bars_in_window(symbol, table):
    """Same shape as run_ltf_trigger_detection.py's load_ltf_bars(), but
    filtered to the shared WINDOW_START (a fixed calendar date the same
    for every symbol/mode in this run) instead of the rolling 2-year
    default -- the whole point of the strict-alignment requirement this
    script enforces."""
    import pymysql
    conn = pymysql.connect(
        host=os.environ.get("DB_HOST", "localhost"), port=int(os.environ.get("DB_PORT", "3308")),
        user=os.environ.get("DB_USER", "quant_user"), password=os.environ.get("DB_PASSWORD", ""),
        database=RAW_DB[symbol], charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, high_price, low_price, close_price FROM `{table}` "
                "WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (WINDOW_START.strftime("%Y-%m-%d %H:%M:%S"),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    for c in ("high_price", "low_price", "close_price"):
        df[c] = df[c].astype(float)
    return df


def floor_for(days):
    return int(round(MIN_TRADES_PER_12_MONTHS * days / 365.25))


def period_metrics(trades, start, end):
    decided = trades[(trades["entry_bar_datetime"] >= start) & (trades["entry_bar_datetime"] < end)]
    decided = decided[decided["exit_reason"].isin(["win", "loss"])]
    r = decided["r_outcome"].astype(float).values
    tm = trade_metrics(r)
    tm["n_decided"] = len(r)
    return tm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=["XAUUSD", "EURUSD"])
    parser.add_argument("--mode", default="choch_only", choices=list(MODES))
    parser.add_argument("--ltf-timeframe", default="m15", choices=["m5", "m15"])
    args = parser.parse_args()
    symbol, mode, ltf_tf = args.symbol, args.mode, args.ltf_timeframe

    grid = list(itertools.product(FRACTION_GRID, MIN_RISK_GRID, MAX_STOP_GRID, CONFIRM_WINDOW_GRID))
    print(f"Grid: {len(FRACTION_GRID)} fraction x {len(MIN_RISK_GRID)} min_risk x "
          f"{len(MAX_STOP_GRID)} max_stop x {len(CONFIRM_WINDOW_GRID)} confirm_window "
          f"= {len(grid)} combinations")

    print(f"Loading {symbol} {ltf_tf}/m5 raw bars (shared window, strict alignment), h1 zones, ATR...")
    ltf_bars = load_bars_in_window(symbol, ltf_tf)
    m5_bars = load_bars_in_window(symbol, "m5") if ltf_tf != "m5" else ltf_bars
    zones = load_zones_raw(symbol)
    zones["created_at_bar"] = pd.to_datetime(zones["created_at_bar"])
    atr_by_h1_bar = load_h1_atr(symbol)

    start, end, train_end, val_end = WINDOW_START, WINDOW_END, TRAIN_END, VAL_END
    total_days = (end - start).total_seconds() / 86400.0
    train_days = (train_end - start).total_seconds() / 86400.0
    val_days = (val_end - train_end).total_seconds() / 86400.0
    test_days = (end - val_end).total_seconds() / 86400.0
    train_floor, val_floor, test_floor = floor_for(train_days), floor_for(val_days), floor_for(test_days)

    print(f"\nShared range (identical across every symbol/mode in this run): {start} -> {end} ({total_days:.0f}d total)")
    print(f"  train: {start} -> {train_end}  ({train_days:.0f}d, floor={train_floor})")
    print(f"  val:   {train_end} -> {val_end}  ({val_days:.0f}d, floor={val_floor})")
    print(f"  test:  {val_end} -> {end}  ({test_days:.0f}d, floor={test_floor})")

    # Triggers depend only on confirmation_window_bars -- compute once per
    # value and reuse across the 27 (fraction, min_risk, max_stop) cells
    # that share it, instead of re-deriving structure 81 times. Cached to
    # disk (pickle) since re-deriving structure is the single most
    # expensive step here -- lets a later run of this script (or a run
    # split across multiple shell calls, needed once for this task since
    # a single foreground call has a hard wall-clock cap) skip straight to
    # the grid evaluation instead of repeating this.
    cache_dir = Path(__file__).parent / ".grid_search_cache"
    cache_dir.mkdir(exist_ok=True)
    triggers_by_window = {}
    for cw in CONFIRM_WINDOW_GRID:
        window_tag = WINDOW_START.strftime("%Y%m%d")
        cache_file = cache_dir / f"triggers_{symbol}_{mode}_{ltf_tf}_cw{cw}_win{window_tag}.pkl"
        if cache_file.exists():
            trig = pd.read_pickle(cache_file)
            print(f"  confirmation_window_bars={cw}: {len(trig)} triggers loaded from cache", flush=True)
        else:
            t0 = time.time()
            eng = LTFTriggerEngine(confirmation_window_bars=cw)
            trig = eng.compute_triggers(ltf_bars, zones, symbol=symbol, ltf_timeframe=ltf_tf, mode=mode)
            trig["confirmed_at_bar"] = pd.to_datetime(trig["confirmed_at_bar"])
            distinct_bars = pd.Series(trig["confirmed_at_bar"].unique())
            entry_by_bar = load_entry_prices(symbol, ltf_tf, distinct_bars)
            trig["entry_price"] = trig["confirmed_at_bar"].map(entry_by_bar)
            trig["atr_14"] = trig["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)
            trig = trig.reset_index(drop=True)
            trig["id"] = trig.index  # simulate() sorts by (confirmed_at_bar, id) as a tiebreaker; synthetic since compute_triggers() doesn't assign real DB ids
            trig.to_pickle(cache_file)
            print(f"  confirmation_window_bars={cw}: {len(trig)} triggers derived in {time.time()-t0:.1f}s", flush=True)
        triggers_by_window[cw] = trig

    results = []
    t0 = time.time()
    for i, (fraction, min_risk, max_stop, cw) in enumerate(grid):
        trig = triggers_by_window[cw]
        targets = compute_structural_targets(
            trig, zones, fraction=fraction, min_risk_atr_multiple=min_risk, max_stop_atr_multiple=max_stop,
        )
        structural = targets[targets["target_status"] == "structural"].copy()
        if structural.empty:
            continue
        trades, skipped = simulate(structural, ltf_bars, m5_bars)

        train_tm = period_metrics(trades, start, train_end)
        val_tm = period_metrics(trades, train_end, val_end)
        test_tm = period_metrics(trades, val_end, end)

        def r_of(period_start, period_end):
            d = trades[(trades["entry_bar_datetime"] >= period_start) & (trades["entry_bar_datetime"] < period_end)]
            d = d[d["exit_reason"].isin(["win", "loss"])]
            return d["r_outcome"].astype(float).values

        train_sharpe = sharpe_ratio(r_of(start, train_end))
        val_sharpe = sharpe_ratio(r_of(train_end, val_end))
        test_sharpe = sharpe_ratio(r_of(val_end, end))

        results.append(dict(
            fraction=fraction, min_risk=min_risk, max_stop=max_stop, confirm_window=cw,
            train_n=train_tm["n_decided"], train_expectancy=train_tm["expectancy_r"],
            train_winrate=train_tm["win_rate"], train_dd=train_tm["max_drawdown_r"], train_sharpe=train_sharpe,
            val_n=val_tm["n_decided"], val_expectancy=val_tm["expectancy_r"],
            val_winrate=val_tm["win_rate"], val_dd=val_tm["max_drawdown_r"], val_sharpe=val_sharpe,
            test_n=test_tm["n_decided"], test_expectancy=test_tm["expectancy_r"],
            test_winrate=test_tm["win_rate"], test_dd=test_tm["max_drawdown_r"], test_sharpe=test_sharpe,
        ))
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(grid)} combos done ({time.time()-t0:.0f}s elapsed)", flush=True)

    report = pd.DataFrame(results)
    pd.set_option("display.width", 220)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}" if isinstance(x, float) else str(x))

    # Step 2: rank by TRAIN expectancy only, among cells that clear the train floor.
    train_ok = report[report["train_n"] >= train_floor].sort_values("train_expectancy", ascending=False)
    print(f"\nCombos clearing train floor ({train_floor}): {len(train_ok)}/{len(report)}")
    print("\nTop 10 by train expectancy:")
    print(train_ok.head(10)[["fraction", "min_risk", "max_stop", "confirm_window",
                              "train_n", "train_expectancy", "train_winrate", "train_dd"]].to_string(index=False))

    default_row = report[
        (report["fraction"] == CURRENT_DEFAULTS["fraction"]) &
        (report["min_risk"] == CURRENT_DEFAULTS["min_risk_atr_multiple"]) &
        (report["max_stop"] == CURRENT_DEFAULTS["max_stop_atr_multiple"]) &
        (report["confirm_window"] == CURRENT_DEFAULTS["confirmation_window_bars"])
    ]
    default_rank = None
    if not default_row.empty:
        default_rank = int((train_ok["train_expectancy"] >= default_row.iloc[0]["train_expectancy"]).sum())
        print(f"\nCurrent production defaults {CURRENT_DEFAULTS}:")
        print(default_row[["train_n", "train_expectancy", "train_winrate", "train_dd"]].to_string(index=False))
        print(f"Rank by train expectancy (among floor-clearing combos): {default_rank} / {len(train_ok)}")

    # Step 3: top 5 candidates from train, evaluated on validation (this is
    # the only stage iteration/reconsideration is allowed at -- test is not
    # touched yet).
    top5 = train_ok.head(5).copy()
    print(f"\nTop {len(top5)} train candidates, evaluated on validation "
          f"(floor={val_floor}):")
    print(top5[["fraction", "min_risk", "max_stop", "confirm_window",
                "val_n", "val_expectancy", "val_winrate", "val_dd"]].to_string(index=False))

    # Step 4: final candidate = best validation expectancy among the top-5
    # train candidates that ALSO clears the validation floor -- if none of
    # the top 5 clears validation, that's reported plainly, not papered over.
    top5_val_ok = top5[top5["val_n"] >= val_floor]
    if top5_val_ok.empty:
        print("\nNone of the top-5 train candidates clear the validation floor "
              f"({val_floor}) -- no reliable winner can be selected from this grid on this data.")
        winner = top5.iloc[0]
        winner_reliable = False
    else:
        winner = top5_val_ok.sort_values("val_expectancy", ascending=False).iloc[0]
        winner_reliable = True

    # Step 5/6: report train/val/test for the winner once, and DSR using
    # the actual number of combinations tested as n_trials (multiple-
    # comparisons correction for the grid search itself, not just a Mode
    # A/B pair the way the other exploratory scripts in this project do it).
    n_trials = len(report)
    train_sr_all = report["train_sharpe"].dropna().values
    sr_variance = float(np.var(train_sr_all, ddof=1)) if len(train_sr_all) >= 2 else 0.0

    # DSR needs the winner's actual train-period R-outcome series (not just
    # its summary Sharpe) -- re-simulate the single winning combo once more
    # to get it, cheap relative to the full grid.
    winner_trig = triggers_by_window[int(winner["confirm_window"])]
    winner_targets = compute_structural_targets(
        winner_trig, zones, fraction=float(winner["fraction"]),
        min_risk_atr_multiple=float(winner["min_risk"]), max_stop_atr_multiple=float(winner["max_stop"]),
    )
    winner_structural = winner_targets[winner_targets["target_status"] == "structural"].copy()
    winner_trades, _ = simulate(winner_structural, ltf_bars, m5_bars)
    winner_train_r = winner_trades[
        (winner_trades["entry_bar_datetime"] >= start) & (winner_trades["entry_bar_datetime"] < train_end) &
        (winner_trades["exit_reason"].isin(["win", "loss"]))
    ]["r_outcome"].astype(float).values
    dsr = deflated_sharpe_ratio(winner_train_r, n_trials=n_trials, sr_variance_across_trials=sr_variance) \
        if len(winner_train_r) >= 2 else None

    print(f"\n{'='*90}\nFINAL CANDIDATE (selected via train->validation, test evaluated once, no iteration after)\n{'='*90}")
    print(f"params: fraction={winner['fraction']} min_risk={winner['min_risk']} "
          f"max_stop={winner['max_stop']} confirm_window={winner['confirm_window']}")
    print(f"reliable (top-5 train candidate clearing validation floor): {winner_reliable}")
    for period in ("train", "val", "test"):
        n = winner[f"{period}_n"]
        floor = {"train": train_floor, "val": val_floor, "test": test_floor}[period]
        print(f"  {period}: n={n} (floor={floor}, {'OK' if n >= floor else 'BELOW FLOOR'})  "
              f"expectancy={winner[f'{period}_expectancy']:.4f}R  win_rate={winner[f'{period}_winrate']:.4f}  "
              f"max_dd={winner[f'{period}_dd']:.4f}R  sharpe={winner[f'{period}_sharpe']:.4f}")
    if dsr is not None:
        print(f"DSR (n_trials={n_trials}, sr_variance_across_trials={sr_variance:.6f}): "
              f"train_sharpe={winner['train_sharpe']:.4f}  dsr={dsr['dsr']}")

    print(f"\nTotal grid search time: {time.time()-t0:.0f}s")

    # File outputs (per this task's explicit ask): timestamped so re-runs
    # accumulate history in git instead of overwriting.
    out_dir = Path(__file__).resolve().parent.parent.parent / "docs" / "optimization_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"{ts}_{symbol}_{mode}_grid.csv"
    report.to_csv(csv_path, index=False)

    md_path = out_dir / f"{ts}_{symbol}_{mode}_ltf_params.md"
    write_markdown_report(
        md_path, symbol, mode, ltf_tf, report, train_ok, top5, winner, winner_reliable,
        default_row, default_rank, n_trials, sr_variance, dsr,
        start, train_end, val_end, end, train_floor, val_floor, test_floor,
    )
    print(f"\nWritten: {md_path}")
    print(f"Written: {csv_path}")


def write_markdown_report(path, symbol, mode, ltf_tf, report, train_ok, top5, winner, winner_reliable,
                           default_row, default_rank, n_trials, sr_variance, dsr,
                           start, train_end, val_end, end, train_floor, val_floor, test_floor):
    def fmt_row(row):
        return (f"| {row['fraction']} | {row['min_risk']} | {row['max_stop']} | {row['confirm_window']} | "
                f"{row['train_n']} | {row['train_expectancy']:.4f} | {row['train_winrate']:.4f} | {row['train_dd']:.4f} |")

    lines = []
    lines.append(f"# LTF structural-TP parameter grid search — {symbol} / {mode} / {ltf_tf}")
    lines.append("")
    lines.append(f"Generated {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')} by "
                 f"`scripts/backtest/grid_search_structural_tp.py`. Exploratory only — "
                 f"not written to `ltf_trigger_signals`/`backtest_runs`.")
    lines.append("")
    lines.append("## Split")
    lines.append("")
    lines.append(f"- Full range: {start} → {end}")
    lines.append(f"- Train (60%): {start} → {train_end}  (floor={train_floor})")
    lines.append(f"- Validation (20%): {train_end} → {val_end}  (floor={val_floor})")
    lines.append(f"- Test (20%): {val_end} → {end}  (floor={test_floor})")
    lines.append("")
    lines.append(f"Grid size: {n_trials} combinations "
                 f"(fraction={[float(x) for x in sorted(report['fraction'].unique())]} × "
                 f"min_risk={[float(x) for x in sorted(report['min_risk'].unique())]} × "
                 f"max_stop={[float(x) for x in sorted(report['max_stop'].unique())]} × "
                 f"confirm_window={[int(x) for x in sorted(report['confirm_window'].unique())]})")
    lines.append("")
    lines.append("## Top 10 by train expectancy (floor-clearing combos only)")
    lines.append("")
    lines.append("| fraction | min_risk | max_stop | confirm_window | train_n | train_expectancy | train_winrate | train_dd |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for _, row in train_ok.head(10).iterrows():
        lines.append(fmt_row(row))
    lines.append("")
    if default_row is not None and not default_row.empty:
        lines.append("## Current production defaults")
        lines.append("")
        lines.append(fmt_row(default_row.iloc[0]))
        lines.append("")
        lines.append(f"Rank by train expectancy among {len(train_ok)} floor-clearing combos: **{default_rank}**")
        lines.append("")
    lines.append("## Top 5 train candidates, evaluated on validation")
    lines.append("")
    lines.append("| fraction | min_risk | max_stop | confirm_window | val_n | val_expectancy | val_winrate | val_dd |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for _, row in top5.iterrows():
        lines.append(f"| {row['fraction']} | {row['min_risk']} | {row['max_stop']} | {row['confirm_window']} | "
                      f"{row['val_n']} | {row['val_expectancy']:.4f} | {row['val_winrate']:.4f} | {row['val_dd']:.4f} |")
    lines.append("")
    lines.append("## Final candidate")
    lines.append("")
    lines.append(f"Selected via train → validation only. Params: fraction={winner['fraction']}, "
                 f"min_risk={winner['min_risk']}, max_stop={winner['max_stop']}, "
                 f"confirm_window={winner['confirm_window']}.")
    lines.append("")
    lines.append(f"**Reliability: {'a validation-floor-clearing top-5 train candidate' if winner_reliable else 'NONE of the top-5 train candidates cleared the validation floor — this candidate is NOT reliable'}.**")
    lines.append("")
    lines.append("| period | n | floor | meets floor | expectancy_r | win_rate | max_dd_r | sharpe |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for period, floor in (("train", train_floor), ("val", val_floor), ("test", test_floor)):
        n = winner[f"{period}_n"]
        lines.append(f"| {period} | {n} | {floor} | {'yes' if n >= floor else '**NO**'} | "
                      f"{winner[f'{period}_expectancy']:.4f} | {winner[f'{period}_winrate']:.4f} | "
                      f"{winner[f'{period}_dd']:.4f} | {winner[f'{period}_sharpe']:.4f} |")
    lines.append("")
    lines.append(f"Train → validation → test gap is the overfitting signal: expectancy "
                 f"{winner['train_expectancy']:.4f}R (train) → {winner['val_expectancy']:.4f}R (val) → "
                 f"{winner['test_expectancy']:.4f}R (test).")
    lines.append("")
    lines.append("## Deflated Sharpe Ratio")
    lines.append("")
    lines.append(f"n_trials = {n_trials} (every grid combination actually tested), "
                 f"sr_variance_across_trials = {sr_variance:.6f} (variance of train-period Sharpe across the grid).")
    lines.append("")
    if dsr is not None:
        lines.append(f"- train Sharpe (plain): {winner['train_sharpe']:.4f}")
        lines.append(f"- DSR (probability true Sharpe exceeds the deflation threshold, "
                     f"corrected for {n_trials} trials): {dsr['dsr']}")
        lines.append(f"- sr0_threshold: {dsr['sr0_threshold']}")
    else:
        lines.append("DSR not computable (insufficient train trades for the winning candidate).")
    lines.append("")
    lines.append("## Multiple-comparisons caveat")
    lines.append("")
    lines.append(f"{n_trials} combinations were tested against the same single-regime "
                 f"~{(end-start).days}-day history. The DSR above corrects for having tried all "
                 f"{n_trials} of them (unlike the Mode-A-vs-B-only correction used elsewhere in this "
                 "project's exploratory scripts) but does not make this a second, independent dataset — "
                 "it is still the same underlying price history the stop-cap fix and min-R:R threshold "
                 "comparisons were also evaluated against.")
    lines.append("")
    lines.append("No change to production defaults is being recommended by this report.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
