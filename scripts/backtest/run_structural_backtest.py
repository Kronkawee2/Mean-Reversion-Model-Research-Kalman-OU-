"""
Runs the structural backtest (analysis/backtester/structural_backtest_engine.py)
against real, persisted LTF trigger signals with a valid structural TP
(target_status='structural' in curated_<symbol>.ltf_trigger_signals) and
computes the full metric set (win rate, profit factor, expectancy,
max drawdown, Sharpe, Deflated Sharpe Ratio) for both the full period and
a held-out out-of-sample test period.

ROLLING WINDOW: both load_structural_triggers() and load_raw_bars() are
bounded to the shared 2-year rolling window (analysis/rolling_window.py,
see docs/DECISIONS.md) as of the h4 MT5-switch-era default-window decision.
This means period_start/period_end -- and therefore the OOS cutoff below --
are recomputed within that shorter window, not against full history; the
'full period' metrics on the dashboard are really "full 2-year window",
not all-time. Full history remains in the DB untouched.

OUT-OF-SAMPLE SPLIT: computed once from the symbol's own raw m15 price
history range (period_start to period_end), cutoff = start + 0.7 *
(end - start), BY CALENDAR TIME, not by trade count -- so the split is
reproducible and doesn't shuffle chronology. The 'test' period is
everything from that cutoff onward, genuinely held out: this script
computes it but nothing upstream (structural TP fraction, ATR floor
multiple, confirmation window, etc.) was ever tuned by looking at it.
FLAGGED PLAINLY: even this held-out period is still within the same
one-directional gold bull-run regime as the training period -- this does
NOT solve the regime-risk problem already flagged in the structural TP
design discussion, it only prevents the strictly worse sin of evaluating
on identical data to whatever was inspected.

Both 'full' and 'test' period metrics come from ONE SINGLE chronological
one-trade-at-a-time simulation across the entire history (see
structural_backtest_engine.py) -- the 'test' period numbers are that same
trade sequence filtered to entry_bar_datetime >= cutoff, not a second,
independently-reset simulation. A position opened before the cutoff can
still be "open" (blocking new entries) after crossing into the test
period, exactly as it would on a real account.

DSR trial set (N=2): for a given symbol, this mode's full-period Sharpe vs
the OTHER mode's full-period Sharpe are the two "trials" -- see
deflated_sharpe.py module docstring for why this is an explicitly rough,
non-robust estimate, not treated as precise.

Usage:
    python scripts/backtest/run_structural_backtest.py --symbol XAUUSD --mode both
    python scripts/backtest/run_structural_backtest.py --symbol EURUSD --mode choch_only --no-write
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

from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402
from analysis.backtester.deflated_sharpe import deflated_sharpe_ratio, trade_metrics  # noqa: E402
from analysis.strategies.ltf_trigger_engine import MODES  # noqa: E402
from analysis.rolling_window import rolling_window_start  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}

MIN_TRADES_PER_12_MONTHS = 200


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def load_structural_triggers(symbol: str, ltf_timeframe: str, mode: str) -> pd.DataFrame:
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, symbol, ltf_timeframe, mode, direction, entry_price, stop_price, "
                "target_price, structural_rr, confirmed_at_bar, htf_zone_type, htf_zone_top, htf_zone_bottom "
                "FROM ltf_trigger_signals WHERE symbol=%s AND ltf_timeframe=%s AND mode=%s "
                "AND target_status='structural' AND confirmed_at_bar >= %s",
                (symbol, ltf_timeframe, mode, rolling_window_start()),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return pd.DataFrame(rows)


def load_raw_bars(symbol: str, timeframe: str) -> pd.DataFrame:
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
    if not df.empty:
        df["price_datetime"] = pd.to_datetime(df["price_datetime"])
        df["high_price"] = df["high_price"].astype(float)
        df["low_price"] = df["low_price"].astype(float)
    return df


def compute_oos_cutoff(m15_bars: pd.DataFrame) -> tuple:
    start = m15_bars["price_datetime"].min()
    end = m15_bars["price_datetime"].max()
    cutoff = start + (end - start) * 0.7
    return start, end, cutoff


def build_period_metrics(trades: pd.DataFrame, other_mode_sharpe: float) -> dict:
    decided = trades[trades["exit_reason"].isin(["win", "loss"])]
    r_outcomes = decided["r_outcome"].tolist()
    tm = trade_metrics(r_outcomes)

    n_trials = 1
    sr_var = None
    if other_mode_sharpe is not None and len(r_outcomes) >= 2:
        from analysis.backtester.deflated_sharpe import sharpe_ratio
        this_sr = sharpe_ratio(np.array(r_outcomes))
        sr_var = float(np.var([this_sr, other_mode_sharpe], ddof=1))
        n_trials = 2
    dsr_result = deflated_sharpe_ratio(
        np.array(r_outcomes), n_trials=n_trials, sr_variance_across_trials=sr_var or 0.0
    )

    n_wins = int((decided["r_outcome"] > 0).sum())
    n_losses = int((decided["r_outcome"] <= 0).sum())
    n_open = int((trades["exit_reason"] == "open_at_data_end").sum())

    resolution = trades["resolution_method"].value_counts().to_dict()
    ambiguous = sum(resolution.get(k, 0) for k in
                     ("m5_drilldown", "m5_still_ambiguous_sl_assumed",
                      "m5_data_missing_sl_assumed", "m5_no_subbar_breach_sl_assumed"))

    return {
        "tm": tm, "dsr": dsr_result, "n_wins": n_wins, "n_losses": n_losses, "n_open": n_open,
        "n_trials_for_dsr": n_trials, "sr_variance_across_trials": sr_var,
        "ambiguous_bar_count": ambiguous,
        "m5_drilldown_count": resolution.get("m5_drilldown", 0),
        "m5_still_ambiguous_count": resolution.get("m5_still_ambiguous_sl_assumed", 0),
        "m5_missing_data_count": resolution.get("m5_data_missing_sl_assumed", 0)
        + resolution.get("m5_no_subbar_breach_sl_assumed", 0),
    }


def persist(symbol, ltf_timeframe, mode, trades, skipped_timestamps, n_signals, start, end, cutoff,
            full_metrics, test_metrics):
    skipped_full = len(skipped_timestamps)
    skipped_test = sum(1 for t in skipped_timestamps if t >= cutoff)
    conn = _conn(SILVER_DB[symbol])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM backtest_trades WHERE symbol=%s AND ltf_timeframe=%s AND mode=%s",
                (symbol, ltf_timeframe, mode),
            )
            cur.execute(
                "DELETE FROM backtest_runs WHERE symbol=%s AND ltf_timeframe=%s AND mode=%s",
                (symbol, ltf_timeframe, mode),
            )

            decided = trades[trades["exit_reason"].isin(["win", "loss"])].sort_values("entry_bar_datetime")
            running = decided["r_outcome"].cumsum()
            running_by_id = dict(zip(decided.index, running))

            trade_sql = """
            INSERT INTO backtest_trades
                (symbol, ltf_timeframe, mode, direction, entry_bar_datetime, entry_price, stop_price,
                 target_price, structural_rr, htf_zone_type, htf_zone_top, htf_zone_bottom,
                 exit_bar_datetime, exit_reason, bars_held, resolution_method, r_outcome, running_equity_r)
            VALUES
                (%(symbol)s, %(ltf_timeframe)s, %(mode)s, %(direction)s, %(entry_bar_datetime)s, %(entry_price)s,
                 %(stop_price)s, %(target_price)s, %(structural_rr)s, %(htf_zone_type)s, %(htf_zone_top)s,
                 %(htf_zone_bottom)s, %(exit_bar_datetime)s, %(exit_reason)s, %(bars_held)s,
                 %(resolution_method)s, %(r_outcome)s, %(running_equity_r)s)
            """
            rows = trades.to_dict("records")
            for i, row in enumerate(rows):
                row["running_equity_r"] = running_by_id.get(trades.index[i])
                for key in ("exit_bar_datetime", "bars_held", "r_outcome", "running_equity_r"):
                    if pd.isna(row.get(key)):
                        row[key] = None
            if rows:
                cur.executemany(trade_sql, rows)

            run_sql = """
            INSERT INTO backtest_runs
                (symbol, ltf_timeframe, mode, period, period_start, period_end, oos_cutoff_date,
                 n_signals_structural, n_trades_taken, n_trades_skipped_overlap, n_wins, n_losses,
                 n_open_at_data_end, win_rate, profit_factor, expectancy_r, max_drawdown_r,
                 sharpe_ratio, skewness, kurtosis, n_trials_for_dsr, sr_variance_across_trials,
                 sr0_threshold, deflated_sharpe_ratio, psr_vs_zero, min_sample_floor_required,
                 meets_min_sample_floor, ambiguous_bar_count, m5_drilldown_count,
                 m5_still_ambiguous_count, m5_missing_data_count)
            VALUES
                (%(symbol)s, %(ltf_timeframe)s, %(mode)s, %(period)s, %(period_start)s, %(period_end)s,
                 %(oos_cutoff_date)s, %(n_signals_structural)s, %(n_trades_taken)s, %(n_trades_skipped_overlap)s,
                 %(n_wins)s, %(n_losses)s, %(n_open_at_data_end)s, %(win_rate)s, %(profit_factor)s,
                 %(expectancy_r)s, %(max_drawdown_r)s, %(sharpe_ratio)s, %(skewness)s, %(kurtosis)s,
                 %(n_trials_for_dsr)s, %(sr_variance_across_trials)s, %(sr0_threshold)s,
                 %(deflated_sharpe_ratio)s, %(psr_vs_zero)s, %(min_sample_floor_required)s,
                 %(meets_min_sample_floor)s, %(ambiguous_bar_count)s, %(m5_drilldown_count)s,
                 %(m5_still_ambiguous_count)s, %(m5_missing_data_count)s)
            """
            for period_name, period_start, period_end, metrics, n_taken in (
                ("full", start, end, full_metrics, len(trades)),
                ("test", cutoff, end, test_metrics, len(trades[trades["entry_bar_datetime"] >= cutoff])),
            ):
                tm = metrics["tm"]
                dsr = metrics["dsr"]
                duration_days = (period_end - period_start).total_seconds() / 86400.0
                floor_required = int(round(MIN_TRADES_PER_12_MONTHS * duration_days / 365.25))
                n_decided = metrics["n_wins"] + metrics["n_losses"]
                row = {
                    "symbol": symbol, "ltf_timeframe": ltf_timeframe, "mode": mode, "period": period_name,
                    "period_start": period_start, "period_end": period_end, "oos_cutoff_date": cutoff,
                    "n_signals_structural": n_signals, "n_trades_taken": n_taken,
                    "n_trades_skipped_overlap": skipped_full if period_name == "full" else skipped_test,
                    "n_wins": metrics["n_wins"], "n_losses": metrics["n_losses"],
                    "n_open_at_data_end": metrics["n_open"],
                    "win_rate": tm["win_rate"], "profit_factor": tm["profit_factor"] if tm["profit_factor"] != float("inf") else None,
                    "expectancy_r": tm["expectancy_r"], "max_drawdown_r": tm["max_drawdown_r"],
                    "sharpe_ratio": dsr["sharpe"], "skewness": dsr["skew"], "kurtosis": dsr["kurtosis"],
                    "n_trials_for_dsr": metrics["n_trials_for_dsr"],
                    "sr_variance_across_trials": metrics["sr_variance_across_trials"],
                    "sr0_threshold": dsr.get("sr0_threshold"), "deflated_sharpe_ratio": dsr.get("dsr"),
                    "psr_vs_zero": dsr.get("psr_vs_zero"),
                    "min_sample_floor_required": floor_required,
                    "meets_min_sample_floor": n_decided >= floor_required,
                    "ambiguous_bar_count": metrics["ambiguous_bar_count"],
                    "m5_drilldown_count": metrics["m5_drilldown_count"],
                    "m5_still_ambiguous_count": metrics["m5_still_ambiguous_count"],
                    "m5_missing_data_count": metrics["m5_missing_data_count"],
                }
                for k, v in row.items():
                    if isinstance(v, float) and (pd.isna(v) or v in (float("inf"), float("-inf"))):
                        row[k] = None
                cur.execute(run_sql, row)
        conn.commit()
    finally:
        conn.close()


def print_report(symbol, mode, period_name, period_start, period_end, metrics, n_taken, skipped_overlap=None):
    tm = metrics["tm"]
    dsr = metrics["dsr"]
    n_decided = metrics["n_wins"] + metrics["n_losses"]
    duration_days = (period_end - period_start).total_seconds() / 86400.0
    floor_required = int(round(MIN_TRADES_PER_12_MONTHS * duration_days / 365.25))
    print(f"\n--- {symbol} / {mode} / {period_name} period ({period_start} -> {period_end}, {duration_days:.0f}d) ---")
    print(f"  trades taken: {n_taken}" + (f"  (skipped for overlap: {skipped_overlap})" if skipped_overlap is not None else ""))
    print(f"  wins={metrics['n_wins']}  losses={metrics['n_losses']}  open_at_data_end={metrics['n_open']}  decided={n_decided}")
    print(f"  win_rate={tm['win_rate']}  profit_factor={tm['profit_factor']}  expectancy_r={tm['expectancy_r']}  max_drawdown_r={tm['max_drawdown_r']}")
    print(f"  sharpe={dsr['sharpe']}  skew={dsr['skew']}  kurtosis={dsr['kurtosis']}")
    print(f"  sr0_threshold={dsr.get('sr0_threshold')}  deflated_sharpe_ratio={dsr.get('dsr')}  psr_vs_zero={dsr.get('psr_vs_zero')}")
    print(f"  min_sample_floor_required={floor_required} (200/12mo scaled)  meets_floor={n_decided >= floor_required}")
    print(f"  resolution: ambiguous_bars={metrics['ambiguous_bar_count']}  m5_drilldown={metrics['m5_drilldown_count']}  "
          f"m5_still_ambiguous={metrics['m5_still_ambiguous_count']}  m5_missing_data={metrics['m5_missing_data_count']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    parser.add_argument("--ltf-timeframe", default="m15", choices=["m5", "m15"])
    parser.add_argument("--mode", default="both", choices=list(MODES) + ["both"])
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} m15/m5 raw bars...")
    m15_bars = load_raw_bars(symbol, args.ltf_timeframe)
    m5_bars = load_raw_bars(symbol, "m5") if args.ltf_timeframe != "m5" else m15_bars
    start, end, cutoff = compute_oos_cutoff(m15_bars)
    print(f"Full period: {start} -> {end}  |  OOS test cutoff (70/30 by calendar time): {cutoff}")

    modes = list(MODES) if args.mode == "both" else [args.mode]
    results_by_mode = {}

    for mode in modes:
        triggers = load_structural_triggers(symbol, args.ltf_timeframe, mode)
        if triggers.empty:
            print(f"[{mode}] No structural triggers found — skipping.")
            continue
        triggers["confirmed_at_bar"] = pd.to_datetime(triggers["confirmed_at_bar"])

        trades, skipped_overlap = simulate(triggers, m15_bars, m5_bars)
        results_by_mode[mode] = (trades, skipped_overlap, len(triggers))

    # First pass: compute each mode's OWN full-period Sharpe (no cross-mode
    # dependency yet) so it can serve as the "other trial" for the DSR of
    # the other mode.
    full_sharpe_by_mode = {}
    from analysis.backtester.deflated_sharpe import sharpe_ratio
    for mode, (trades, _, _) in results_by_mode.items():
        decided = trades[trades["exit_reason"].isin(["win", "loss"])]
        full_sharpe_by_mode[mode] = sharpe_ratio(np.array(decided["r_outcome"].tolist())) if len(decided) >= 2 else None

    for mode, (trades, skipped_overlap, n_signals) in results_by_mode.items():
        other_modes = [m for m in results_by_mode if m != mode]
        other_sharpe = full_sharpe_by_mode.get(other_modes[0]) if other_modes else None

        full_trades = trades
        test_trades = trades[trades["entry_bar_datetime"] >= cutoff]

        full_metrics = build_period_metrics(full_trades, other_sharpe)
        test_metrics = build_period_metrics(test_trades, other_sharpe)

        skipped_test_count = sum(1 for t in skipped_overlap if t >= cutoff)
        print_report(symbol, mode, "FULL", start, end, full_metrics, len(full_trades), len(skipped_overlap))
        print_report(symbol, mode, "TEST (held-out)", cutoff, end, test_metrics, len(test_trades), skipped_test_count)

        if not args.no_write:
            persist(symbol, args.ltf_timeframe, mode, trades, skipped_overlap, n_signals,
                    start, end, cutoff, full_metrics, test_metrics)
            print(f"[{mode}] Persisted {len(trades)} trades + 2 backtest_runs rows (full, test)")


if __name__ == "__main__":
    main()
