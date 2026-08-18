"""
Unit tests for analysis.strategies.confluence_ltf_trigger -- specifically
the core-first-fallback-to-full range selection rule (approved design,
see docs/DECISIONS.md): a confirmed trigger uses the confluence zone's
CORE range if the LTF entry price lands inside it, else falls back to
FULL range, matching a single-factor zone's existing behavior.

Reuses the exact same bullish reversal candle sequence validated in
test_confluence_zone_engine.py (real BULLISH_CHOCH fires with close=114
partway through the sequence) -- only the confluence zone's own
core_range boundary changes between test cases, since that's the only
thing this rule depends on.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.strategies.confluence_ltf_trigger import compute_confluence_triggers  # noqa: E402


def _ltf_bars(rows, freq="15min"):
    n = len(rows)
    dt = pd.date_range("2026-01-01", periods=n, freq=freq)
    return pd.DataFrame({
        "price_datetime": dt,
        "high_price": [r[1] for r in rows],
        "low_price":  [r[2] for r in rows],
        "close_price": [r[3] for r in rows],
    })


# Same reversal sequence as test_confluence_zone_engine.py's
# _TREND_REVERSAL_ROWS: downtrend to a swing low near 88, then a violent
# bullish break -- BULLISH_CHOCH fires at row 13 with close=114.
_ROWS = [
    (100.0, 101.0, 99.0, 100.5),
    (100.5, 102.0, 100.0, 101.5),
    (101.5, 103.0, 101.0, 102.5),
    (102.5, 103.0, 97.0, 97.5),
    (97.5, 98.0, 94.0, 94.5),
    (94.5, 95.0, 90.0, 90.5),
    (90.5, 93.0, 90.0, 92.5),
    (92.5, 94.0, 91.0, 93.5),
    (93.5, 95.0, 92.0, 94.5),
    (94.5, 95.0, 88.0, 89.0),
    (89.0, 91.0, 88.0, 90.5),
    (90.5, 93.0, 89.0, 91.5),
    (91.5, 95.0, 90.0, 93.5),
    (93.5, 115.0, 92.0, 114.0),   # BULLISH_CHOCH here, close=114
    (114.0, 118.0, 113.5, 117.0),
    (117.0, 122.0, 116.5, 121.0),
]

_CREATED_AT = pd.Timestamp("2026-01-01 00:00") - pd.Timedelta(hours=2)


def _zone(zone_id, core_top, core_bottom, full_top=130.0, full_bottom=88.0, mode="mode_a_2factor"):
    return pd.DataFrame([{
        "id": zone_id, "mode": mode, "direction": "bullish",
        "zone_full_top": full_top, "zone_full_bottom": full_bottom,
        "zone_core_top": core_top, "zone_core_bottom": core_bottom,
        "last_factor_at_bar": _CREATED_AT, "status": "active", "resolved_at_bar": None,
    }])


def test_core_confirms_when_entry_price_lands_inside_core_range():
    print("=" * 60)
    print("1. entry price inside core_range -> zone_range_used='core', boundaries swapped to core")
    print("=" * 60)
    bars = _ltf_bars(_ROWS)
    # close=114 at the CHoCH bar sits inside [110, 130].
    zones = _zone(zone_id=1, core_top=130.0, core_bottom=110.0)
    trig = compute_confluence_triggers(bars, zones, symbol="TEST", ltf_timeframe="m15", mode="choch_only")

    assert not trig.empty, "expected at least one confirmed trigger"
    row = trig.iloc[0]
    assert row["entry_price"] == 114.0
    assert row["zone_range_used"] == "core", f"expected core, got {row['zone_range_used']}"
    assert row["htf_zone_top"] == 130.0 and row["htf_zone_bottom"] == 110.0, \
        "htf_zone_top/bottom must be swapped to the CORE boundary, not left at FULL"
    assert row["confluence_zone_id"] == 1
    assert row["htf_zone_type"] == "confluence_bullish_mode_a"
    assert row["zone_source"] == "confluence_zone"
    print(f"  [+] entry={row['entry_price']}  range_used={row['zone_range_used']}  "
          f"zone=[{row['htf_zone_bottom']}, {row['htf_zone_top']}]")
    print("  [OK] test_core_confirms_when_entry_price_lands_inside_core_range PASSED\n")


def test_falls_back_to_full_when_entry_price_outside_core_range():
    print("=" * 60)
    print("2. entry price outside core_range but inside full_range -> zone_range_used='full', matches current single-factor-zone behavior")
    print("=" * 60)
    bars = _ltf_bars(_ROWS)
    # close=114 sits BELOW this core_range's bottom (116) -- only full [88,130] catches it.
    zones = _zone(zone_id=2, core_top=130.0, core_bottom=116.0)
    trig = compute_confluence_triggers(bars, zones, symbol="TEST", ltf_timeframe="m15", mode="choch_only")

    assert not trig.empty, "expected at least one confirmed trigger"
    row = trig.iloc[0]
    assert row["entry_price"] == 114.0
    assert row["zone_range_used"] == "full", f"expected full, got {row['zone_range_used']}"
    assert row["htf_zone_top"] == 130.0 and row["htf_zone_bottom"] == 88.0, \
        "htf_zone_top/bottom must stay at the FULL boundary when entry isn't inside core"
    assert row["confluence_zone_id"] == 2
    print(f"  [+] entry={row['entry_price']}  range_used={row['zone_range_used']}  "
          f"zone=[{row['htf_zone_bottom']}, {row['htf_zone_top']}]")
    print("  [OK] test_falls_back_to_full_when_entry_price_outside_core_range PASSED\n")


def test_mode_a_and_mode_b_htf_zone_type_differ_for_the_same_underlying_cluster():
    print("=" * 60)
    print("3. mode_a and mode_b triggers from the SAME cluster timing get distinct htf_zone_type values (regression: they used to collide and silently merge)")
    print("=" * 60)
    bars = _ltf_bars(_ROWS)
    # Same id-space collision setup a mode_b_3factor zone would create in
    # practice: a mode_b zone is always also a mode_a zone of the same
    # cluster, sharing last_factor_at_bar (and therefore touch/CHoCH bars).
    zone_a = _zone(zone_id=10, core_top=130.0, core_bottom=110.0, mode="mode_a_2factor")
    zone_b = _zone(zone_id=11, core_top=130.0, core_bottom=110.0, mode="mode_b_3factor")

    trig_a = compute_confluence_triggers(bars, zone_a, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    trig_b = compute_confluence_triggers(bars, zone_b, symbol="TEST", ltf_timeframe="m15", mode="choch_only")

    assert trig_a.iloc[0]["htf_zone_type"] == "confluence_bullish_mode_a"
    assert trig_b.iloc[0]["htf_zone_type"] == "confluence_bullish_mode_b"
    assert trig_a.iloc[0]["htf_zone_type"] != trig_b.iloc[0]["htf_zone_type"], \
        "mode_a and mode_b triggers must get different htf_zone_type values, or ltf_trigger_signals' uq_trigger " \
        "unique key can't tell them apart and one silently overwrites the other on upsert"
    print(f"  [+] mode_a htf_zone_type={trig_a.iloc[0]['htf_zone_type']}  mode_b htf_zone_type={trig_b.iloc[0]['htf_zone_type']}")
    print("  [OK] test_mode_a_and_mode_b_htf_zone_type_differ_for_the_same_underlying_cluster PASSED\n")


def test_no_zones_returns_empty():
    print("=" * 60)
    print("4. empty confluence_zones input returns an empty frame, not an error")
    print("=" * 60)
    bars = _ltf_bars(_ROWS)
    empty_zones = pd.DataFrame(columns=["id", "mode", "direction", "zone_full_top", "zone_full_bottom",
                                         "zone_core_top", "zone_core_bottom", "last_factor_at_bar",
                                         "status", "resolved_at_bar"])
    trig = compute_confluence_triggers(bars, empty_zones, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    assert trig.empty
    print("  [OK] test_no_zones_returns_empty PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   CONFLUENCE LTF TRIGGER — UNIT TESTS")
    print("#" * 60 + "\n")

    test_core_confirms_when_entry_price_lands_inside_core_range()
    test_falls_back_to_full_when_entry_price_outside_core_range()
    test_mode_a_and_mode_b_htf_zone_type_differ_for_the_same_underlying_cluster()
    test_no_zones_returns_empty()

    print("#" * 60)
    print("   ALL CONFLUENCE LTF TRIGGER TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
