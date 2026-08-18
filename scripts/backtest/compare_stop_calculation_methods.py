"""
Exploratory comparison of 3 stop-calculation methods for
structural_tp_engine.py, target selection held IDENTICAL across all 3 (only
the stop side changes) -- confirmed with the user as a side-by-side data
gathering pass, NOT a decision (no method is picked or recommended here).

Methods tested (see analysis/strategies/structural_tp_engine.py for the
mechanism of each):
  baseline           stop_mode='zone_far_edge' (current production) -- far
                      edge of the trigger's OWN htf_zone.
  nearest            stop_mode='nearest_structure' -- searches ALL causally-
                      active zones of the SAME direction as the trigger (not
                      just the one that fired) for the nearest genuine
                      structural invalidation point, using the identical
                      nearest-causal-zone search mechanism already used for
                      target selection, mirrored to the near/support side.
  middle_ground      stop_mode='nearest_structure' + widen_to_min_risk=True
                      -- same as 'nearest' but a stop tighter than the
                      EXISTING MIN_RISK_ATR_MULTIPLE floor (0.5x ATR-14,
                      already used elsewhere in this engine) is widened to
                      exactly that floor distance instead of being skipped
                      as 'stop_too_tight'. Reuses an existing constant
                      rather than introducing a new tunable one.
  mae_75pct          stop_mode='atr' with atr_stop_multiple set EMPIRICALLY
                      per (symbol, mode) from the 75th percentile of
                      Maximum Adverse Excursion (MAE, in ATR-14 multiples)
                      across every WINNING trade in the current baseline --
                      i.e. "how far did price realistically pull back
                      before winning trades worked out, historically."
                      Computed once (see the MAE section below) and passed
                      in as MAE_ATR_MULTIPLE_75TH. Structural-geometry-free
                      -- no zone reference at all, purely data-driven.

MAE (Maximum Adverse Excursion) computation for mae_75pct, done separately
before this script (see scripts/backtest/../../scratch MAE computation --
not itself part of the regular pipeline): for every WINNING trade in the
current baseline (backtest_trades, exit_reason='win'), walked the real m15
bars between (entry_bar_datetime, exit_bar_datetime] to find how far price
moved against the position at its worst point, normalized by the h1 ATR-14
at entry (not raw price -- gold ranged $2500-$5500 across this dataset, so
a fixed price distance would be systematically wrong at one end or the
other; ATR-normalization is the same convention structural_tp_engine.py
already uses for MIN/MAX_STOP_ATR_MULTIPLE). 75th percentile chosen as the
headline threshold: it means the stop would have let 75% of this dataset's
actual winning trades survive their real worst drawdown to reach target,
while staying meaningfully tighter than the 90-95th percentile tail (which
is dominated by rare, large pullback outliers and would produce an
excessively wide, low-information stop). 80th percentile is a reasonable,
slightly more conservative alternative (fewer winners cut off, wider
stop) -- both percentiles are reported in the MAE distribution output;
only 75th is carried through to a full backtest variant here to keep the
comparison to 4 methods as requested.

REAL CONCERN WITH THIS METHOD, STATED PLAINLY, NOT HIDDEN: this MAE
distribution is computed ONLY from winning trades (survivorship bias by
construction). It says nothing about what LOSING trades' adverse
excursions look like -- a stop sized to let 75% of winners survive might
also be far wider than what most losing trades needed to be stopped out
profitably-early, or it might barely change the loss population at all.
Tuning a stop purely to "keep winners alive" without also looking at how
it would have changed the losers' outcomes is a real, one-sided piece of
information, not a complete picture -- the backtest re-run below is what
actually reveals whether the wider stop's cost (bigger losses, since 1R
is now a larger distance) outweighs the benefit (fewer premature exits).

Runs through the exact same StructuralTPEngine -> backtest pipeline as
run_structural_backtest.py -- same triggers, same htf zones, same raw bars,
same concurrent-trades-allowed / unlimited-holding-period simulation
(analysis/backtester/structural_backtest_engine.py, current production
behavior as of this pass -- see docs/DECISIONS.md). NOT written to
backtest_trades/backtest_runs -- exploratory only, computed in-memory.

MULTIPLE-COMPARISONS CAVEAT: testing 3 stop methods against the same
history is itself a form of multiple comparisons, same caveat as
compare_structural_tp_variants.py. No DSR/statistical correction is applied
across the 3 methods here -- this script reports raw performance numbers
for a joint human decision, not a statistically-adjusted verdict.

Usage:
    python scripts/backtest/compare_stop_calculation_methods.py --symbol XAUUSD --mode both
    python scripts/backtest/compare_stop_calculation_methods.py --symbol EURUSD --mode choch_sweep
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.structural_tp_engine import compute_structural_targets  # noqa: E402
from analysis.strategies.ltf_trigger_engine import MODES  # noqa: E402
from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402
from analysis.backtester.deflated_sharpe import trade_metrics  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}

VARIANTS = {
    "baseline":      dict(stop_mode="zone_far_edge",     widen_to_min_risk=False),
    "nearest":       dict(stop_mode="nearest_structure",  widen_to_min_risk=False),
    "middle_ground": dict(stop_mode="nearest_structure",  widen_to_min_risk=True),
    # mae_75pct's atr_stop_multiple is symbol/mode-specific (see
    # MAE_ATR_MULTIPLE_75TH below) -- filled in per (symbol, mode) at
    # variant-run time, not a single shared constant. widen_to_min_risk=True
    # is a technical necessity, not a methodology choice: XAUUSD choch_sweep's
    # empirical multiple (0.4926) sits fractionally BELOW the existing
    # MIN_RISK_ATR_MULTIPLE floor (0.5) -- without this, every single
    # trigger for that one combo would be flagged stop_too_tight and
    # skipped, since the "too tight" check compares against a floor that's
    # marginally wider than what this method computed. Widening in that one
    # case moves the effective stop from 0.4926x to 0.5x ATR -- a ~1.5%
    # difference, not a real change to the method's intent.
    "mae_75pct":     dict(stop_mode="atr", widen_to_min_risk=True),
}

# 75th percentile of Maximum Adverse Excursion (in h1 ATR-14 multiples)
# across every WINNING trade in the current baseline, per (symbol, mode) --
# computed once from real backtest_trades + raw m15 data (see module
# docstring's MAE section). Not re-derived live by this script (that
# computation walks the full m15 history per winning trade and is slow) --
# treat as a snapshot tied to the baseline dataset this was computed
# against; re-run the MAE computation if the baseline trade set changes
# materially.
MAE_ATR_MULTIPLE_75TH = {
    ("XAUUSD", "choch_only"): 0.508603,
    ("XAUUSD", "choch_sweep"): 0.492638,
    ("EURUSD", "choch_only"): 0.524014,
    ("EURUSD", "choch_sweep"): 0.525502,
}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_all_triggers(symbol, ltf_timeframe, mode):
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, symbol, ltf_timeframe, mode, direction, confirmed_at_bar, "
                "htf_zone_type, htf_zone_top, htf_zone_bottom "
                "FROM ltf_trigger_signals WHERE symbol=%s AND ltf_timeframe=%s AND mode=%s "
                "AND zone_source='smc_signals' AND target_zone_source='smc_signals' "
                "AND confirmed_at_bar >= %s",
                (symbol, ltf_timeframe, mode, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_htf_zones(symbol):
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT zone_type, zone_top, zone_bottom, created_at_bar, invalidated_at_bar "
                "FROM smc_signals WHERE symbol=%s AND timeframe='h1' AND created_at_bar >= %s",
                (symbol, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_raw_bars(symbol, timeframe):
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, high_price, low_price FROM `{timeframe}` "
                "WHERE price_datetime >= %s ORDER BY price_datetime ASC",
                (rolling_window_start(),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    df["price_datetime"] = pd.to_datetime(df["price_datetime"])
    for c in ("high_price", "low_price"):
        df[c] = df[c].astype(float)
    return df


def load_h1_atr(symbol):
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT bar_datetime, atr_14 FROM features WHERE symbol=%s AND timeframe='h1' AND bar_datetime >= %s",
                (symbol, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {r["bar_datetime"]: float(r["atr_14"]) for r in rows}


def load_entry_prices(symbol, ltf_timeframe, distinct_bars):
    conn = _conn(RAW_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT price_datetime, close_price FROM `{ltf_timeframe}` "
                f"WHERE price_datetime IN ({','.join(['%s'] * len(distinct_bars))})",
                tuple(distinct_bars.tolist()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {r["price_datetime"]: float(r["close_price"]) for r in rows}


def run_variant(cfg, triggers_base, zones, m15_bars, m5_bars, entry_by_bar, atr_by_h1_bar):
    triggers = triggers_base.copy()
    triggers["entry_price"] = triggers["confirmed_at_bar"].map(entry_by_bar)
    triggers["atr_14"] = triggers["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)

    targets = compute_structural_targets(triggers, zones, **cfg)
    targets["id"] = triggers["id"].values

    structural = targets[targets["target_status"] == "structural"].copy()
    n_structural = len(structural)
    n_stop_too_tight = int((targets["target_status"] == "stop_too_tight").sum())

    if structural.empty:
        return None

    trades, _ = simulate(structural, m15_bars, m5_bars)
    decided = trades[trades["exit_reason"].isin(["win", "loss"])]

    return {"n_structural": n_structural, "n_stop_too_tight": n_stop_too_tight,
            "trades": trades, "decided": decided}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--ltf-timeframe", default="m15", choices=["m5", "m15"])
    parser.add_argument("--mode", default="both", choices=list(MODES) + ["both"])
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} data (raw bars, h1 zones, ATR, triggers)...")
    m15_bars = load_raw_bars(symbol, args.ltf_timeframe)
    m5_bars = load_raw_bars(symbol, "m5") if args.ltf_timeframe != "m5" else m15_bars
    zones = load_htf_zones(symbol)
    atr_by_h1_bar = load_h1_atr(symbol)

    modes = list(MODES) if args.mode == "both" else [args.mode]

    rows = []
    for mode in modes:
        triggers_base = load_all_triggers(symbol, args.ltf_timeframe, mode)
        if triggers_base.empty:
            print(f"[{mode}] No triggers found, skipping.")
            continue
        triggers_base["confirmed_at_bar"] = pd.to_datetime(triggers_base["confirmed_at_bar"])
        distinct_bars = pd.Series(triggers_base["confirmed_at_bar"].unique())
        entry_by_bar = load_entry_prices(symbol, args.ltf_timeframe, distinct_bars)

        for variant_name, cfg in VARIANTS.items():
            cfg = dict(cfg)
            if variant_name == "mae_75pct":
                cfg["atr_stop_multiple"] = MAE_ATR_MULTIPLE_75TH[(symbol, mode)]
            print(f"Running {mode} / {variant_name}"
                  + (f" (atr_stop_multiple={cfg['atr_stop_multiple']:.4f})" if variant_name == "mae_75pct" else "")
                  + "...")
            result = run_variant(cfg, triggers_base, zones, m15_bars, m5_bars, entry_by_bar, atr_by_h1_bar)
            if result is None:
                print(f"  [{mode}/{variant_name}] No structural triggers produced — skipped.")
                continue

            r = result["decided"]["r_outcome"].astype(float).values
            tm = trade_metrics(r.tolist())
            rr = result["decided"]["structural_rr"].astype(float)

            rows.append({
                "mode": mode, "variant": variant_name,
                "n_structural": result["n_structural"], "n_stop_too_tight": result["n_stop_too_tight"],
                "trades_taken": len(result["trades"]), "n_decided": len(result["decided"]),
                "win_rate": tm["win_rate"], "profit_factor": tm["profit_factor"],
                "expectancy_r": tm["expectancy_r"], "max_drawdown_r": tm["max_drawdown_r"],
                "rr_min": float(rr.min()) if len(rr) else None,
                "rr_median": float(rr.median()) if len(rr) else None,
                "rr_max": float(rr.max()) if len(rr) else None,
            })

    report = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}" if isinstance(x, float) else str(x))
    for mode in modes:
        print(f"\n{'='*110}\n{symbol} / {mode}\n{'='*110}")
        sub = report[report["mode"] == mode].drop(columns=["mode"])
        print(sub.to_string(index=False))

    print("\n" + "=" * 110)
    print("MULTIPLE-COMPARISONS CAVEAT: 3 stop-calculation methods were tested against the same")
    print("single-regime history, target selection held identical throughout. No statistical")
    print("correction is applied across the 3 methods -- this is raw performance data for a")
    print("joint decision, not a statistically-adjusted verdict. No method is recommended here.")
    print("=" * 110)


if __name__ == "__main__":
    main()
