"""
Structural Backtest Engine: turns confirmed LTF trigger signals (with a
valid structural TP) into an actual, measurable sequence of simulated
trades -- bar-by-bar, walk-forward, no lookahead.

Design decisions confirmed with the user before building (propose-and-
justify, same discipline as every other phase):

1. OUTCOME DETERMINATION -- walk forward on m15 bars from confirmed_at_bar
   (exclusive; the first bar that could hit SL/TP is the one AFTER entry).
   AMBIGUOUS BAR (a single m15 bar's high-low range contains BOTH stop and
   target): drill into that bar's three constituent m5 sub-bars and check
   them in chronological order -- the first sub-bar that breaches either
   level (and not both) resolves the trade. If a sub-bar is STILL
   ambiguous (rare -- would need an m15-scale move within 5 minutes), or
   m5 data is missing for that window entirely, fall back to a CONSERVATIVE
   assumption: stop-loss hit first. This never overstates performance --
   the failure mode of the fallback is undercounting wins, not inflating
   them. Every resolution is tagged with HOW it was resolved
   (resolution_method) so the fallback rate is visible and auditable, not
   hidden inside an aggregate win rate.
   MAX HOLDING PERIOD -- none. A trade walks forward until it resolves or
   the available price history runs out (exit_reason='open_at_data_end' in
   that case). No arbitrary cap is introduced, deliberately, matching the
   "fewest tunable parameters" reasoning already applied to Option 2 for
   structural TP -- but this means a trade CAN take an unusually long time
   to resolve. The holding-period distribution is reported so any
   pathologically long trade is visible, not silently absorbed into an
   average.

   An intraday (21:00 UTC) time-stop was tried and REVERTED -- see
   docs/DECISIONS.md. It was added to fix a near-100%-win-rate artifact
   found while testing a realistic (300-1000pt) stop-distance floor, but
   the user clarified they hold trades until TP/SL by their own discretion,
   not on a forced day-trading schedule -- the backtest should not simulate
   a holding behavior they don't actually use. If a stop-distance-realism
   question needs re-testing, it needs a different fix than a forced
   time-based exit.

2. OVERLAPPING TRADES -- unrestricted. Every valid trigger (target_status=
   'structural') is simulated as its OWN independent trade, regardless of
   whether another trade from the same (symbol, mode) is still open at that
   moment. This replaces an earlier one-trade-at-a-time (single-position)
   constraint that was removed deliberately -- see docs/DECISIONS.md -- to
   fix a real sample-size problem: skipping every signal that overlapped an
   already-open trade was shrinking the realized trade count far below the
   raw signal count (commonly skipping 70-90%+ of qualifying triggers),
   which is what caused several stop-distance-floor test variants to fail
   this project's own statistical sample-size floor even though there was
   no shortage of raw signals. Simulating every trigger independently fixes
   the sample-size problem without changing how any individual trade
   resolves (still walk-forward, still TP/SL/open_at_data_end only, still
   no lookahead) -- it only changes which signals get a simulated trade at
   all. This does NOT model a capital/margin constraint (a real account may
   not actually be able to hold N simultaneous positions) -- that's a
   capital-management question this project has flagged elsewhere as not
   yet built, not something this backtest engine claims to answer.

This module does not touch analysis/backtester/backtest.py (an earlier,
unrelated MTFStrategyEngine-signal backtester already in this package) --
additive, new file, following this project's established convention.
"""

import numpy as np
import pandas as pd

RESOLUTION_METHODS = (
    "m15_clean", "m5_drilldown", "m5_still_ambiguous_sl_assumed",
    "m5_data_missing_sl_assumed", "m5_no_subbar_breach_sl_assumed", "open_at_data_end",
)

TRADE_COLUMNS = [
    "source_trigger_id", "symbol", "ltf_timeframe", "mode", "direction",
    "entry_bar_datetime", "entry_price", "stop_price", "target_price", "structural_rr",
    "htf_zone_type", "htf_zone_top", "htf_zone_bottom",
    "exit_bar_datetime", "exit_reason", "bars_held", "resolution_method", "r_outcome",
]


def _hit_tp(direction, high, low, target):
    return high >= target if direction == "bullish" else low <= target


def _hit_sl(direction, high, low, stop):
    return low <= stop if direction == "bullish" else high >= stop


def _walk_forward(direction, entry_bar_time, stop, target, m15_bars, m5_bars):
    """
    m15_bars / m5_bars: DataFrames with price_datetime, high_price, low_price,
    already sorted ascending, filtered to price_datetime > entry_bar_time
    is done by the caller for m15 (m5_bars is passed in full and sliced
    per-ambiguous-bar here).
    Returns dict: exit_bar_datetime, exit_reason, bars_held, resolution_method.
    """
    for bars_held, row in enumerate(m15_bars.itertuples(index=False), start=1):
        h, l, t = float(row.high_price), float(row.low_price), row.price_datetime
        tp = _hit_tp(direction, h, l, target)
        sl = _hit_sl(direction, h, l, stop)

        if tp and not sl:
            return {"exit_bar_datetime": t, "exit_reason": "win", "bars_held": bars_held,
                    "resolution_method": "m15_clean"}
        if sl and not tp:
            return {"exit_bar_datetime": t, "exit_reason": "loss", "bars_held": bars_held,
                    "resolution_method": "m15_clean"}
        if not sl and not tp:
            continue

        # Ambiguous: both levels fall within this single m15 bar's range.
        # Drill into its 3 constituent m5 sub-bars to find which was hit first.
        window_start = t - pd.Timedelta(minutes=15)
        sub = m5_bars[(m5_bars["price_datetime"] > window_start) & (m5_bars["price_datetime"] <= t)]
        if sub.empty:
            return {"exit_bar_datetime": t, "exit_reason": "loss", "bars_held": bars_held,
                    "resolution_method": "m5_data_missing_sl_assumed"}

        for srow in sub.itertuples(index=False):
            sh, sl_lo, st = float(srow.high_price), float(srow.low_price), srow.price_datetime
            s_tp = _hit_tp(direction, sh, sl_lo, target)
            s_sl = _hit_sl(direction, sh, sl_lo, stop)
            if s_tp and not s_sl:
                return {"exit_bar_datetime": st, "exit_reason": "win", "bars_held": bars_held,
                        "resolution_method": "m5_drilldown"}
            if s_sl and not s_tp:
                return {"exit_bar_datetime": st, "exit_reason": "loss", "bars_held": bars_held,
                        "resolution_method": "m5_drilldown"}
            if s_sl and s_tp:
                return {"exit_bar_datetime": st, "exit_reason": "loss", "bars_held": bars_held,
                        "resolution_method": "m5_still_ambiguous_sl_assumed"}

        # Defensive fallback: the parent m15 bar was ambiguous but no
        # individual m5 sub-bar breached either level (can happen with
        # partial m5 coverage of the window). Conservative SL assumption.
        return {"exit_bar_datetime": t, "exit_reason": "loss", "bars_held": bars_held,
                "resolution_method": "m5_no_subbar_breach_sl_assumed"}

    return {"exit_bar_datetime": None, "exit_reason": "open_at_data_end", "bars_held": None,
            "resolution_method": "open_at_data_end"}


def simulate(triggers: pd.DataFrame, m15_bars: pd.DataFrame, m5_bars: pd.DataFrame) -> tuple:
    """
    triggers: structural-only LTF trigger rows (target_status='structural'),
        must have symbol, ltf_timeframe, mode, direction, entry_price,
        stop_price, target_price, structural_rr, confirmed_at_bar,
        htf_zone_type, htf_zone_top, htf_zone_bottom, id (persisted as
        source_trigger_id on the output trade -- with concurrent trades now
        allowed, two different HTF zones can genuinely share the same
        confirmed_at_bar, so entry_bar_datetime alone is no longer a unique
        identifier for a trade; the source trigger's own id is).
    m15_bars / m5_bars: raw OHLC (price_datetime, high_price, low_price),
        sorted ascending -- the FULL series, not pre-filtered.
    Returns (trades_df, skipped_timestamps). Every trigger is now simulated
    independently (see module docstring, #2) -- skipped_timestamps is
    always empty, kept in the return signature so callers that unpack
    (trades, skipped) don't need to change.
    """
    m15 = m15_bars.sort_values("price_datetime").reset_index(drop=True)
    m5 = m5_bars.sort_values("price_datetime").reset_index(drop=True)

    ordered = triggers.sort_values(["confirmed_at_bar", "id"]).reset_index(drop=True)

    trades = []
    skipped_timestamps = []

    for _, trig in ordered.iterrows():
        entry_bar_time = pd.Timestamp(trig["confirmed_at_bar"])

        direction = trig["direction"]
        stop = float(trig["stop_price"])
        target = float(trig["target_price"])
        future_m15 = m15[m15["price_datetime"] > entry_bar_time]

        outcome = _walk_forward(direction, entry_bar_time, stop, target, future_m15, m5)

        if outcome["exit_reason"] == "win":
            r_outcome = float(trig["structural_rr"])
        elif outcome["exit_reason"] == "loss":
            r_outcome = -1.0
        else:
            r_outcome = None

        trades.append({
            "source_trigger_id": trig["id"],
            "symbol": trig["symbol"], "ltf_timeframe": trig["ltf_timeframe"], "mode": trig["mode"],
            "direction": direction, "entry_bar_datetime": entry_bar_time,
            "entry_price": float(trig["entry_price"]), "stop_price": stop, "target_price": target,
            "structural_rr": float(trig["structural_rr"]),
            "htf_zone_type": trig["htf_zone_type"], "htf_zone_top": float(trig["htf_zone_top"]),
            "htf_zone_bottom": float(trig["htf_zone_bottom"]),
            "exit_bar_datetime": outcome["exit_bar_datetime"], "exit_reason": outcome["exit_reason"],
            "bars_held": outcome["bars_held"], "resolution_method": outcome["resolution_method"],
            "r_outcome": r_outcome,
        })

    trades_df = pd.DataFrame(trades, columns=TRADE_COLUMNS) if trades else pd.DataFrame(columns=TRADE_COLUMNS)
    return trades_df, skipped_timestamps
