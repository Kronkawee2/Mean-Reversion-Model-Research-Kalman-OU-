"""
Exploratory comparison of structural TP stop/target definitions against the
same train/test split and backtest mechanics already established
(run_structural_backtest.py) -- confirmed with the user as a diagnostic
into WHY the baseline backtest shows a "win often, lose big" profile
(median structural R:R=0.235, avg win ~0.32R needing ~3 wins to offset one
-1R loss), not a tuning exercise. Variants are recomputed IN-MEMORY from
the same raw triggers/zones/entry/ATR data and are NOT written back to
ltf_trigger_signals or backtest_runs/backtest_trades -- the production
baseline tables are untouched by running this script.

Variants tested:
  baseline        stop=zone far edge, STRUCTURAL_TP_FRACTION=0.85 (current production)
  atr_stop_1.5x   stop=entry -/+ 1.5x ATR-14, fraction=0.85 (same target logic)
  frac_0.70       stop=zone far edge (baseline), fraction=0.70
  frac_1.00       stop=zone far edge (baseline), fraction=1.00

Each variant is independently re-run through the exact same
StructuralTPEngine -> LTFTriggerEngine-derived triggers -> backtest
pipeline (same one-trade-at-a-time simulation, same 70/30 calendar-time
train/test cutoff, same metric set) as the production baseline.

MULTIPLE-COMPARISONS CAVEAT (explicitly required by the user, not
optional): testing 4 variants against the same ~6-month, single-regime
history is itself a form of multiple comparisons. The Deflated Sharpe
Ratio computed for each variant corrects for exactly ONE dimension of
that -- the Mode A vs Mode B selection within a given variant (N=2 in
every DSR call below, unchanged from the production script) -- it does
NOT know that 4 stop/target definitions were tried side by side here and
does not deflate across THAT dimension. A variant that looks best in this
table has not been shown to be more real than the others; it may simply
be the one that fits this specific 6-month bull-run window best. No
variant is picked as a winner in this script's output.

Usage:
    python scripts/backtest/compare_structural_tp_variants.py --symbol XAUUSD --mode both
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
from analysis.backtester.deflated_sharpe import deflated_sharpe_ratio, trade_metrics, sharpe_ratio  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}

VARIANTS = {
    "baseline":      dict(stop_mode="zone_far_edge", fraction=0.85, atr_stop_multiple=None),
    "atr_stop_1.5x": dict(stop_mode="atr",            fraction=0.85, atr_stop_multiple=1.5),
    "frac_0.70":     dict(stop_mode="zone_far_edge", fraction=0.70, atr_stop_multiple=None),
    "frac_1.00":     dict(stop_mode="zone_far_edge", fraction=1.00, atr_stop_multiple=None),
}


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_all_triggers(symbol, ltf_timeframe, mode):
    """ALL triggers regardless of baseline target_status -- each variant
    recomputes its own target_status from scratch, so a trigger the
    baseline marked stop_too_tight might be structural under another
    variant, and vice versa."""
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, symbol, ltf_timeframe, mode, direction, confirmed_at_bar, "
                "htf_zone_type, htf_zone_top, htf_zone_bottom "
                "FROM ltf_trigger_signals WHERE symbol=%s AND ltf_timeframe=%s AND mode=%s "
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


def run_variant(variant_name, cfg, triggers_base, zones, m15_bars, m5_bars, entry_by_bar, atr_by_h1_bar, cutoff):
    triggers = triggers_base.copy()
    triggers["entry_price"] = triggers["confirmed_at_bar"].map(entry_by_bar)
    triggers["atr_14"] = triggers["confirmed_at_bar"].dt.floor("h").map(atr_by_h1_bar)

    kwargs = dict(fraction=cfg["fraction"], stop_mode=cfg["stop_mode"])
    if cfg["atr_stop_multiple"] is not None:
        kwargs["atr_stop_multiple"] = cfg["atr_stop_multiple"]

    targets = compute_structural_targets(triggers, zones, **kwargs)
    targets["id"] = triggers["id"].values

    structural = targets[targets["target_status"] == "structural"].copy()
    n_structural = len(structural)
    n_stop_too_tight = int((targets["target_status"] == "stop_too_tight").sum())

    if structural.empty:
        return None

    trades, skipped = simulate(structural, m15_bars, m5_bars)
    full_decided = trades[trades["exit_reason"].isin(["win", "loss"])]
    test_trades = trades[trades["entry_bar_datetime"] >= cutoff]
    test_decided = test_trades[test_trades["exit_reason"].isin(["win", "loss"])]

    return {
        "n_structural": n_structural, "n_stop_too_tight": n_stop_too_tight,
        "full_trades": trades, "full_decided": full_decided,
        "test_trades": test_trades, "test_decided": test_decided,
    }


def summarize(decided_r, n_trials, sr_variance):
    r = decided_r["r_outcome"].astype(float).values if len(decided_r) else np.array([])
    tm = trade_metrics(r)
    dsr = deflated_sharpe_ratio(r, n_trials=n_trials, sr_variance_across_trials=sr_variance or 0.0)
    return tm, dsr


def persist(symbol: str, ltf_timeframe: str, rows: list):
    """Persists this exploratory comparison to tp_variant_comparison so the
    dashboard can show it without re-running the comparison live -- NOT the
    same table as backtest_runs (the real, adopted results), kept
    deliberately separate. Full delete+reinsert per (symbol, ltf_timeframe),
    same "re-simulation can change row counts" reasoning as backtest_trades."""
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tp_variant_comparison WHERE symbol=%s AND ltf_timeframe=%s",
                (symbol, ltf_timeframe),
            )
            sql = """
            INSERT INTO tp_variant_comparison
                (symbol, ltf_timeframe, mode, variant, period, n_structural, n_stop_too_tight,
                 trades_taken, n_decided, win_rate, profit_factor, expectancy_r, max_drawdown_r,
                 sharpe_ratio, deflated_sharpe_ratio)
            VALUES
                (%(symbol)s, %(ltf_timeframe)s, %(mode)s, %(variant)s, %(period)s, %(n_structural)s,
                 %(n_stop_too_tight)s, %(trades_taken)s, %(n_decided)s, %(win_rate)s, %(profit_factor)s,
                 %(expectancy_r)s, %(max_drawdown_r)s, %(sharpe)s, %(dsr)s)
            """
            db_rows = []
            for row in rows:
                r = dict(row)
                r["symbol"] = symbol
                r["ltf_timeframe"] = ltf_timeframe
                for k in ("win_rate", "profit_factor", "expectancy_r", "max_drawdown_r", "sharpe", "dsr"):
                    if pd.isna(r.get(k)) or r.get(k) in (float("inf"), float("-inf")):
                        r[k] = None
                db_rows.append(r)
            cur.executemany(sql, db_rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--ltf-timeframe", default="m15", choices=["m5", "m15"])
    parser.add_argument("--mode", default="both", choices=list(MODES) + ["both"])
    parser.add_argument("--write", action="store_true",
                         help="persist to tp_variant_comparison (off by default -- this script is "
                              "exploratory, not part of the regular pipeline)")
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} data (raw bars, h1 zones, ATR, triggers)...")
    m15_bars = load_raw_bars(symbol, args.ltf_timeframe)
    m5_bars = load_raw_bars(symbol, "m5") if args.ltf_timeframe != "m5" else m15_bars
    zones = load_htf_zones(symbol)
    atr_by_h1_bar = load_h1_atr(symbol)
    start = m15_bars["price_datetime"].min()
    end = m15_bars["price_datetime"].max()
    cutoff = start + (end - start) * 0.7
    print(f"Period: {start} -> {end}  |  OOS cutoff: {cutoff}")

    modes = list(MODES) if args.mode == "both" else [args.mode]

    all_results = {}  # (mode, variant) -> result dict
    for mode in modes:
        triggers_base = load_all_triggers(symbol, args.ltf_timeframe, mode)
        if triggers_base.empty:
            print(f"[{mode}] No triggers found, skipping.")
            continue
        triggers_base["confirmed_at_bar"] = pd.to_datetime(triggers_base["confirmed_at_bar"])
        distinct_bars = pd.Series(triggers_base["confirmed_at_bar"].unique())
        entry_by_bar = load_entry_prices(symbol, args.ltf_timeframe, distinct_bars)

        for variant_name, cfg in VARIANTS.items():
            print(f"Running {mode} / {variant_name}...")
            result = run_variant(variant_name, cfg, triggers_base, zones, m15_bars, m5_bars,
                                  entry_by_bar, atr_by_h1_bar, cutoff)
            all_results[(mode, variant_name)] = result

    # DSR trial set per variant: this mode's Sharpe vs the OTHER mode's
    # Sharpe, WITHIN that same variant -- unchanged in spirit from the
    # production script (N=2, not compared across variants).
    full_sharpe = {}
    for (mode, variant_name), result in all_results.items():
        if result is None:
            continue
        r = result["full_decided"]["r_outcome"].astype(float).values
        full_sharpe[(mode, variant_name)] = sharpe_ratio(r) if len(r) >= 2 else None

    rows = []
    for (mode, variant_name), result in all_results.items():
        if result is None:
            print(f"[{mode}/{variant_name}] No structural triggers produced by this variant — skipped.")
            continue
        other_modes = [m for m in modes if m != mode]
        other_sharpe = full_sharpe.get((other_modes[0], variant_name)) if other_modes else None
        n_trials = 2 if other_sharpe is not None else 1

        full_tm, full_dsr = summarize(
            result["full_decided"], n_trials,
            float(np.var([full_sharpe[(mode, variant_name)], other_sharpe], ddof=1))
            if other_sharpe is not None and full_sharpe.get((mode, variant_name)) is not None else None,
        )
        test_tm, test_dsr = summarize(
            result["test_decided"], n_trials,
            float(np.var([full_sharpe[(mode, variant_name)], other_sharpe], ddof=1))
            if other_sharpe is not None and full_sharpe.get((mode, variant_name)) is not None else None,
        )

        for period_name, tm, dsr, decided, taken in (
            ("full", full_tm, full_dsr, result["full_decided"], len(result["full_trades"])),
            ("test", test_tm, test_dsr, result["test_decided"], len(result["test_trades"])),
        ):
            rows.append({
                "mode": mode, "variant": variant_name, "period": period_name,
                "n_structural": result["n_structural"], "n_stop_too_tight": result["n_stop_too_tight"],
                "trades_taken": taken, "n_decided": len(decided),
                "win_rate": tm["win_rate"], "profit_factor": tm["profit_factor"],
                "expectancy_r": tm["expectancy_r"], "max_drawdown_r": tm["max_drawdown_r"],
                "sharpe": dsr["sharpe"], "dsr": dsr["dsr"],
            })

    report = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    pd.set_option("display.float_format", lambda x: f"{x:.4f}" if isinstance(x, float) else str(x))
    for mode in modes:
        print(f"\n{'='*100}\n{symbol} / {mode}\n{'='*100}")
        sub = report[report["mode"] == mode].drop(columns=["mode"])
        print(sub.to_string(index=False))

    print("\n" + "=" * 100)
    print("MULTIPLE-COMPARISONS CAVEAT: 4 variants were tested against the same single-regime")
    print("history. The DSR values above correct only for the Mode A vs Mode B selection WITHIN")
    print("each variant (N=2) -- they do NOT correct for having tried 4 stop/target definitions")
    print("side by side here. No variant is being recommended.")
    print("=" * 100)

    if args.write:
        n = persist(symbol, args.ltf_timeframe, rows)
        print(f"\nPersisted {n} rows to `{SILVER_DB[symbol]}`.tp_variant_comparison")


if __name__ == "__main__":
    main()
