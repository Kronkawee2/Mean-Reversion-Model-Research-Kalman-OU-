"""
Unit tests for LTFTriggerEngine (analysis/strategies/ltf_trigger_engine.py).

Core requirement being validated: Mode A ('choch_only') fires on a zone
touch + matching-direction CHoCH alone; Mode B ('choch_sweep') additionally
requires a liquidity sweep (in the same direction) that precedes the CHoCH,
within the same confirmation window. Both scenarios below share the exact
same price/CHoCH structure -- only the presence of an engineered sweep
differs -- so the difference in each mode's output is attributable to the
sweep requirement alone, not incidental differences in test data.

Price series construction (hand-verified via direct execution against
SMCStructureEngine before being locked in here, same discipline as this
project's other structure-detection tests): a clean up-leg, down-leg,
up-leg, down-leg, up-leg zigzag with pivot_window=3. This produces a
confirmed BEARISH_CHOCH at bar 23 (close=88) and a confirmed BULLISH_CHOCH
at bar 31 (close=112) -- the bullish one is what the test zone targets.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.strategies.ltf_trigger_engine import LTFTriggerEngine  # noqa: E402

CLOSES = (
    [90, 92, 94, 96, 98, 100, 102] +      # leg1 up, peak@6=102
    [100, 98, 96, 94, 92, 90] +           # leg2 down, trough@12=90
    [93, 96, 99, 102, 105, 108] +         # leg3 up, peak@18=108
    [104, 100, 96, 92, 88, 84] +          # leg4 down, trough@24=84 -> BEARISH_CHOCH@23
    [88, 92, 96, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 142]  # leg5 up -> BULLISH_CHOCH@31
)


def _bars(lows_override=None):
    dt = pd.date_range("2026-01-01 00:00", periods=len(CLOSES), freq="15min")
    highs = [c + 1 for c in CLOSES]
    lows = [c - 1 for c in CLOSES]
    if lows_override:
        for idx, val in lows_override.items():
            lows[idx] = val
    return pd.DataFrame({"price_datetime": dt, "high_price": highs, "low_price": lows, "close_price": CLOSES})


def _bullish_zone(top=92.0, bottom=82.0):
    dt0 = pd.Timestamp("2026-01-01 00:00")
    return pd.DataFrame([{
        "zone_type": "order_block_bullish", "zone_top": top, "zone_bottom": bottom,
        "created_at_bar": dt0, "invalidated_at_bar": None,
    }])


def test_mode_a_fires_without_sweep_mode_b_does_not():
    print("=" * 60)
    print("1. Mode A (choch_only) fires on zone touch + CHoCH alone;")
    print("   Mode B (choch_sweep) does NOT fire when no sweep exists")
    print("=" * 60)

    bars = _bars()
    zones = _bullish_zone()
    engine = LTFTriggerEngine()

    out_a = engine.compute_triggers(bars, zones, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    out_b = engine.compute_triggers(bars, zones, symbol="TEST", ltf_timeframe="m15", mode="choch_sweep")

    assert len(out_a) == 1, f"expected 1 Mode A trigger, got {len(out_a)}"
    assert out_a.iloc[0]["direction"] == "bullish"
    assert out_a.iloc[0]["choch_bar_datetime"] == pd.Timestamp("2026-01-01 07:45:00")
    assert out_a.iloc[0]["sweep_bar_datetime"] is None

    assert len(out_b) == 0, f"expected 0 Mode B triggers (no sweep present), got {len(out_b)}"

    print(f"  [+] Mode A: 1 trigger (touch={out_a.iloc[0]['touch_bar_datetime']}, choch={out_a.iloc[0]['choch_bar_datetime']})")
    print(f"  [+] Mode B: 0 triggers (correctly rejected -- no sweep in the window)")
    print("  [OK] test_mode_a_fires_without_sweep_mode_b_does_not PASSED\n")


def test_mode_b_fires_when_sweep_precedes_choch():
    print("=" * 60)
    print("2. Mode B fires once a qualifying sweep (same direction, before")
    print("   the CHoCH, within the window) is added -- same price/CHoCH")
    print("   structure as test 1, only the engineered sweep differs")
    print("=" * 60)

    bars = _bars(lows_override={19: 85.0})  # SSL sweep: low wicks below the 89 swing low, close (104) stays above it
    zones = _bullish_zone()
    engine = LTFTriggerEngine()

    out_a = engine.compute_triggers(bars, zones, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    out_b = engine.compute_triggers(bars, zones, symbol="TEST", ltf_timeframe="m15", mode="choch_sweep")

    assert len(out_a) == 1, "Mode A must be unaffected by the sweep -- still fires the same way"
    assert len(out_b) == 1, f"expected 1 Mode B trigger now that a qualifying sweep exists, got {len(out_b)}"

    row = out_b.iloc[0]
    assert row["sweep_bar_datetime"] == pd.Timestamp("2026-01-01 04:45:00")
    assert row["sweep_type"] == "ssl"
    assert row["sweep_bar_datetime"] <= row["choch_bar_datetime"], "sweep must precede (or coincide with) the CHoCH"
    assert row["confirmed_at_bar"] == row["choch_bar_datetime"], "confirmed_at_bar must be the LATEST of touch/choch/sweep"

    print(f"  [+] Mode B: 1 trigger, sweep@{row['sweep_bar_datetime']} precedes choch@{row['choch_bar_datetime']}")
    print("  [OK] test_mode_b_fires_when_sweep_precedes_choch PASSED\n")


def test_choch_direction_must_match_zone_direction():
    print("=" * 60)
    print("3. A zone only confirms on a CHoCH matching its OWN expected")
    print("   direction -- this series has both a BEARISH_CHOCH (bar 23)")
    print("   and a BULLISH_CHOCH (bar 31); a bearish zone touching the")
    print("   same price range must reference the bearish one, never the")
    print("   bullish one, even though both are within its window")
    print("=" * 60)

    bars = _bars()
    dt0 = pd.Timestamp("2026-01-01 00:00")
    bearish_zone = pd.DataFrame([{
        "zone_type": "order_block_bearish", "zone_top": 92.0, "zone_bottom": 82.0,
        "created_at_bar": dt0, "invalidated_at_bar": None,
    }])
    engine = LTFTriggerEngine()

    out = engine.compute_triggers(bars, bearish_zone, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    assert len(out) == 1, f"expected exactly 1 trigger (matching the bearish CHoCH), got {len(out)}"
    row = out.iloc[0]
    assert row["direction"] == "bearish"
    assert row["choch_bar_datetime"] == pd.Timestamp("2026-01-01 05:45:00"), "must reference the BEARISH_CHOCH at bar 23, not the bullish one at bar 31"

    print(f"  [+] 1 trigger, correctly anchored to the bearish CHoCH (choch={row['choch_bar_datetime']}), not the bullish one")
    print("  [OK] test_choch_direction_must_match_zone_direction PASSED\n")


def test_touch_outside_confirmation_window_does_not_fire():
    print("=" * 60)
    print("4. A zone touch far outside the confirmation window from any")
    print("   matching CHoCH must not produce a trigger")
    print("=" * 60)

    bars = _bars()
    dt0 = pd.Timestamp("2026-01-01 00:00")
    # This zone's price range (89-91) is genuinely revisited multiple times
    # by this zigzag series (verified directly: touches at bar indices
    # 0,1,11,12,22,23,25,26) -- its NEAREST touch to the bar-31 BULLISH_CHOCH
    # is bar 26, 5 bars away. A window of 2 puts every touch outside range.
    zone = pd.DataFrame([{
        "zone_type": "order_block_bullish", "zone_top": 91.0, "zone_bottom": 89.0,
        "created_at_bar": dt0, "invalidated_at_bar": None,
    }])
    engine = LTFTriggerEngine(confirmation_window_bars=2)  # tight window; nearest real touch is 5 bars away

    out = engine.compute_triggers(bars, zone, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    assert len(out) == 0, f"touch outside the confirmation window must not fire, got {len(out)} triggers"

    print("  [+] 0 triggers -- nearest touch (bar 26) is 5 bars from the CHoCH, outside the 2-bar window")
    print("  [OK] test_touch_outside_confirmation_window_does_not_fire PASSED\n")


def test_touch_within_formation_hour_rejected_same_touch_accepted_once_zone_predates_it():
    print("=" * 60)
    print("5. Regression: a touch inside the zone's own formation h1 hour")
    print("   must be rejected -- found via real data (36.2% of choch_only")
    print("   signals were touches inside the zone's own formation hour,")
    print("   32.4% exactly equal to it). The SAME underlying touch bar (26,")
    print("   2026-01-01 06:30) is used in both cases below -- only the")
    print("   zone's created_at_bar differs -- to isolate the fix.")
    print("=" * 60)

    bars = _bars()
    dt_choch = pd.Timestamp("2026-01-01 05:45:00")  # BEARISH_CHOCH @ bar 23

    # Zone "formed" at bar 22 (05:30) -> formation closes at 06:30. The bar-26
    # touch (06:30) lands exactly AT formation close, i.e. after the h1
    # formation bar has fully closed -- must be accepted.
    zone_formed_early = pd.DataFrame([{
        "zone_type": "order_block_bearish", "zone_top": 92.0, "zone_bottom": 82.0,
        "created_at_bar": pd.Timestamp("2026-01-01 05:30:00"), "invalidated_at_bar": None,
    }])
    engine = LTFTriggerEngine()
    accepted = engine.compute_triggers(bars, zone_formed_early, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    assert len(accepted) == 1, f"touch after formation-hour-close must be accepted, got {len(accepted)} triggers"
    assert accepted.iloc[0]["touch_bar_datetime"] == pd.Timestamp("2026-01-01 06:30:00")
    assert accepted.iloc[0]["choch_bar_datetime"] == dt_choch
    print(f"  [+] zone created 05:30 -> formation closes 06:30 -- touch@06:30 ACCEPTED (1 trigger)")

    # Same zone shape, but "formed" at bar 26 (06:30) itself -- the exact same
    # bar-26 touch now falls INSIDE its own formation hour (06:30-07:30) and
    # must be rejected. No other touch exists in this zone's range after
    # 07:30 in this series, so the zone must produce zero triggers.
    zone_formed_at_touch = pd.DataFrame([{
        "zone_type": "order_block_bearish", "zone_top": 92.0, "zone_bottom": 82.0,
        "created_at_bar": pd.Timestamp("2026-01-01 06:30:00"), "invalidated_at_bar": None,
    }])
    rejected = engine.compute_triggers(bars, zone_formed_at_touch, symbol="TEST", ltf_timeframe="m15", mode="choch_only")
    assert len(rejected) == 0, f"touch inside the zone's own formation hour must be rejected, got {len(rejected)} triggers"
    print(f"  [+] zone created 06:30 -> formation closes 07:30 -- touch@06:30 REJECTED (0 triggers)")

    print("  [OK] test_touch_within_formation_hour_rejected_same_touch_accepted_once_zone_predates_it PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   LTF TRIGGER ENGINE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_mode_a_fires_without_sweep_mode_b_does_not()
    test_mode_b_fires_when_sweep_precedes_choch()
    test_choch_direction_must_match_zone_direction()
    test_touch_outside_confirmation_window_does_not_fire()
    test_touch_within_formation_hour_rejected_same_touch_accepted_once_zone_predates_it()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
