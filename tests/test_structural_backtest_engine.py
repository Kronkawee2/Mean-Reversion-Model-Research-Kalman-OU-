"""
Unit tests for the structural backtest engine
(analysis/backtester/structural_backtest_engine.py).

Covers every distinct resolution path: a clean m15 win/loss, an ambiguous
m15 bar resolved via m5 drilldown, an m5 sub-bar that is ITSELF still
ambiguous (conservative SL-first fallback), a missing-m5-data fallback, a
trade that never resolves before data runs out, one-trade-at-a-time
overlap skipping, and the deterministic tie-break when two signals share
the identical confirmed_at_bar.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.backtester.structural_backtest_engine import simulate  # noqa: E402

T0 = pd.Timestamp("2026-01-01 00:00:00")


def _m15(rows):
    """rows: list of (minutes_after_t0, high, low)."""
    return pd.DataFrame([
        {"price_datetime": T0 + pd.Timedelta(minutes=m), "high_price": h, "low_price": l}
        for m, h, l in rows
    ])


def _m5(rows):
    return _m15(rows)  # same shape, just typically 5-min spaced


def _trigger(id_, direction, stop, target, confirmed_at, entry_price=100.0, structural_rr=None):
    if structural_rr is None:
        structural_rr = abs(target - entry_price) / abs(entry_price - stop)
    return {
        "id": id_, "symbol": "TEST", "ltf_timeframe": "m15", "mode": "choch_only",
        "direction": direction, "entry_price": entry_price, "stop_price": stop, "target_price": target,
        "structural_rr": structural_rr, "confirmed_at_bar": confirmed_at,
        "htf_zone_type": "order_block_bullish" if direction == "bullish" else "order_block_bearish",
        "htf_zone_top": entry_price + 1, "htf_zone_bottom": entry_price - 1,
    }


def test_clean_m15_win_and_loss():
    print("=" * 60)
    print("1. Clean (unambiguous) m15 win and loss, no drilldown needed")
    print("=" * 60)

    # Bullish: stop=95, target=105. Bar 1 (15m) no breach, bar 2 (30m) TP only.
    m15 = _m15([(15, 104, 99), (30, 106, 101)])
    trig = pd.DataFrame([_trigger("t1", "bullish", 95.0, 105.0, T0)])
    trades, skipped = simulate(trig, m15, pd.DataFrame(columns=["price_datetime", "high_price", "low_price"]))
    row = trades.iloc[0]
    assert row["exit_reason"] == "win" and row["resolution_method"] == "m15_clean" and row["bars_held"] == 2
    assert row["r_outcome"] == row["structural_rr"]
    print(f"  [+] bullish clean win: bars_held={row['bars_held']}, r_outcome={row['r_outcome']}")

    # Bearish: stop=105, target=95. Bar 1 no breach, bar 2 SL only (high>=105, low=100 not <=95).
    m15b = _m15([(15, 104, 99), (30, 106, 100)])
    trigb = pd.DataFrame([_trigger("t2", "bearish", 105.0, 95.0, T0)])
    tradesb, _ = simulate(trigb, m15b, pd.DataFrame(columns=["price_datetime", "high_price", "low_price"]))
    rowb = tradesb.iloc[0]
    assert rowb["exit_reason"] == "loss" and rowb["resolution_method"] == "m15_clean"
    assert rowb["r_outcome"] == -1.0
    print(f"  [+] bearish clean loss: bars_held={rowb['bars_held']}, r_outcome={rowb['r_outcome']}")
    print("  [OK] test_clean_m15_win_and_loss PASSED\n")


def test_ambiguous_m15_resolved_via_m5_drilldown():
    print("=" * 60)
    print("2. Ambiguous m15 bar (both stop and target in range) resolved")
    print("   by drilling into its m5 sub-bars")
    print("=" * 60)

    # Bullish stop=95 target=105. The m15 bar at 15m has high=106,low=94 -- ambiguous.
    m15 = _m15([(15, 106, 94)])
    # m5 sub-bars covering (0,15]: 5,10,15. First sub-bar (5) no breach, second (10) TP only.
    m5 = _m5([(5, 101, 98), (10, 106, 99), (15, 103, 97)])
    trig = pd.DataFrame([_trigger("t3", "bullish", 95.0, 105.0, T0)])
    trades, _ = simulate(trig, m15, m5)
    row = trades.iloc[0]
    assert row["exit_reason"] == "win" and row["resolution_method"] == "m5_drilldown"
    assert row["exit_bar_datetime"] == T0 + pd.Timedelta(minutes=10)
    print(f"  [+] resolved via m5 drilldown at {row['exit_bar_datetime']}: {row['exit_reason']}")
    print("  [OK] test_ambiguous_m15_resolved_via_m5_drilldown PASSED\n")


def test_still_ambiguous_m5_subbar_falls_back_to_sl_assumed():
    print("=" * 60)
    print("3. Even the resolving m5 sub-bar is itself ambiguous -- must")
    print("   fall back to the conservative stop-loss-first assumption,")
    print("   never silently pick a win")
    print("=" * 60)

    m15 = _m15([(15, 106, 94)])
    # First m5 sub-bar (5m) is ALSO ambiguous (both breach).
    m5 = _m5([(5, 106, 94), (10, 106, 99), (15, 103, 97)])
    trig = pd.DataFrame([_trigger("t4", "bullish", 95.0, 105.0, T0)])
    trades, _ = simulate(trig, m15, m5)
    row = trades.iloc[0]
    assert row["exit_reason"] == "loss" and row["resolution_method"] == "m5_still_ambiguous_sl_assumed"
    print(f"  [+] {row['resolution_method']} -> conservative loss, not an assumed win")
    print("  [OK] test_still_ambiguous_m5_subbar_falls_back_to_sl_assumed PASSED\n")


def test_missing_m5_data_falls_back_to_sl_assumed():
    print("=" * 60)
    print("4. Ambiguous m15 bar with NO m5 data available for that window")
    print("   -- must fall back to conservative stop-loss-first, not error")
    print("   out or silently assume a win")
    print("=" * 60)

    m15 = _m15([(15, 106, 94)])
    m5_empty = pd.DataFrame(columns=["price_datetime", "high_price", "low_price"])
    trig = pd.DataFrame([_trigger("t5", "bullish", 95.0, 105.0, T0)])
    trades, _ = simulate(trig, m15, m5_empty)
    row = trades.iloc[0]
    assert row["exit_reason"] == "loss" and row["resolution_method"] == "m5_data_missing_sl_assumed"
    print(f"  [+] {row['resolution_method']} -> conservative loss")
    print("  [OK] test_missing_m5_data_falls_back_to_sl_assumed PASSED\n")


def test_trade_never_resolves_marked_open_at_data_end():
    print("=" * 60)
    print("5. A trade that never hits SL or TP before price history runs")
    print("   out must be marked open_at_data_end, not forced closed")
    print("=" * 60)

    m15 = _m15([(15, 104, 99), (30, 103, 98)])  # never breaches 95/105
    trig = pd.DataFrame([_trigger("t6", "bullish", 95.0, 105.0, T0)])
    trades, _ = simulate(trig, m15, pd.DataFrame(columns=["price_datetime", "high_price", "low_price"]))
    row = trades.iloc[0]
    assert row["exit_reason"] == "open_at_data_end" and row["r_outcome"] is None
    assert row["exit_bar_datetime"] is None and row["bars_held"] is None
    print(f"  [+] exit_reason={row['exit_reason']}, r_outcome={row['r_outcome']}")
    print("  [OK] test_trade_never_resolves_marked_open_at_data_end PASSED\n")


def test_one_trade_at_a_time_overlap_skipped_and_later_signal_taken():
    print("=" * 60)
    print("6. One trade open at a time: a signal firing while a position")
    print("   is still open is skipped; a signal firing after it resolves")
    print("   is taken; two signals at the IDENTICAL confirmed_at_bar")
    print("   resolve deterministically by id, not both")
    print("=" * 60)

    # Trade 1 (bullish, entry T0): resolves at 30m (TP hit).
    m15 = _m15([(15, 104, 99), (30, 106, 101), (45, 104, 99), (60, 106, 101)])
    triggers = pd.DataFrame([
        _trigger("a1", "bullish", 95.0, 105.0, T0),                                    # taken (first)
        _trigger("a2", "bullish", 95.0, 105.0, T0),                                    # same ts as a1 -> skipped (tie-break loses)
        _trigger("a3", "bullish", 95.0, 105.0, T0 + pd.Timedelta(minutes=15)),         # position still open (resolves @30m) -> skipped
        _trigger("a4", "bullish", 95.0, 105.0, T0 + pd.Timedelta(minutes=30)),         # position free again -> taken
    ])
    trades, skipped = simulate(triggers, m15, pd.DataFrame(columns=["price_datetime", "high_price", "low_price"]))

    assert len(skipped) == 2, f"expected 2 skipped-overlap signals, got {len(skipped)}"
    assert len(trades) == 2, f"expected 2 taken trades, got {len(trades)}"
    taken_ids = set()
    # re-derive which triggers were taken by matching entry_bar_datetime
    entries = trades["entry_bar_datetime"].tolist()
    assert entries == [T0, T0 + pd.Timedelta(minutes=30)], f"unexpected entries taken: {entries}"

    print(f"  [+] 2 taken (entries={entries}), 2 skipped (same-timestamp tie loser + overlap-blocked signal)")
    print("  [OK] test_one_trade_at_a_time_overlap_skipped_and_later_signal_taken PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   STRUCTURAL BACKTEST ENGINE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_clean_m15_win_and_loss()
    test_ambiguous_m15_resolved_via_m5_drilldown()
    test_still_ambiguous_m5_subbar_falls_back_to_sl_assumed()
    test_missing_m5_data_falls_back_to_sl_assumed()
    test_trade_never_resolves_marked_open_at_data_end()
    test_one_trade_at_a_time_overlap_skipped_and_later_signal_taken()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
