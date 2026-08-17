"""
Unit tests for StructuralTPEngine (analysis/strategies/structural_tp_engine.py).

Core requirements validated: (1) a clear nearby opposing zone produces a
tight structural R:R computed directly from entry/stop/target, not a chosen
number; (2) no eligible opposing zone triggers the fallback (skip: NULL
target/rr, target_status='no_opposing_zone'), never a default ratio; (3) the
opposing-zone search is causal -- a zone created AFTER the trigger's
confirmed_at_bar, or already invalidated by confirmed_at_bar, must never be
selected even when it would produce a tighter (more attractive) R:R than
the correct causally-valid zone.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.strategies.structural_tp_engine import compute_structural_targets  # noqa: E402

CONFIRMED = pd.Timestamp("2026-01-01 12:00:00")


def _bullish_trigger(entry=100.0, own_zone_top=99.0, own_zone_bottom=95.0, confirmed_at=CONFIRMED, atr_14=1.0):
    # atr_14 default (1.0) is far below any test's risk distance (5.0), so
    # it never triggers the stop-too-tight floor unless a test deliberately
    # sets a larger atr_14 to test that floor.
    return pd.DataFrame([{
        "direction": "bullish", "htf_zone_top": own_zone_top, "htf_zone_bottom": own_zone_bottom,
        "confirmed_at_bar": confirmed_at, "entry_price": entry, "atr_14": atr_14,
    }])


def test_clear_nearby_opposing_zone_produces_tight_structural_rr():
    print("=" * 60)
    print("1. A clear, nearby opposing zone produces a tight structural")
    print("   R:R -- computed from entry/stop/target, not chosen")
    print("=" * 60)

    trigger = _bullish_trigger(entry=100.0, own_zone_bottom=95.0)  # stop=95, risk=5
    zones = pd.DataFrame([{
        "zone_type": "order_block_bearish", "zone_top": 115.0, "zone_bottom": 110.0,
        "created_at_bar": pd.Timestamp("2026-01-01 06:00:00"), "invalidated_at_bar": None,
    }])

    out = compute_structural_targets(trigger, zones)
    row = out.iloc[0]

    assert row["target_status"] == "structural"
    assert row["stop_price"] == 95.0
    # near edge = zone_bottom (110, first boundary price reaches from below)
    # reward_full = 110-100=10, reward = 0.85*10=8.5, target=108.5
    assert abs(row["target_price"] - 108.5) < 1e-9
    # rr = reward/risk = 8.5/5 = 1.7
    assert abs(row["structural_rr"] - 1.7) < 1e-9
    assert row["opposing_zone_type"] == "order_block_bearish"

    print(f"  [+] entry=100 stop=95 opposing_near_edge=110 -> target={row['target_price']} rr={row['structural_rr']}")
    print("  [OK] test_clear_nearby_opposing_zone_produces_tight_structural_rr PASSED\n")


def test_no_opposing_zone_triggers_skip_fallback_not_a_default_ratio():
    print("=" * 60)
    print("2. No eligible opposing zone -> skip fallback (NULL target/rr,")
    print("   target_status='no_opposing_zone'), never a default R:R")
    print("=" * 60)

    trigger = _bullish_trigger(entry=100.0, own_zone_bottom=95.0)
    # Only a bearish zone BELOW entry (not ahead of price) and a bullish
    # (same-direction, not opposing) zone above -- neither is an eligible
    # opposing zone.
    zones = pd.DataFrame([
        {"zone_type": "order_block_bearish", "zone_top": 90.0, "zone_bottom": 85.0,
         "created_at_bar": pd.Timestamp("2026-01-01 06:00:00"), "invalidated_at_bar": None},
        {"zone_type": "order_block_bullish", "zone_top": 120.0, "zone_bottom": 115.0,
         "created_at_bar": pd.Timestamp("2026-01-01 06:00:00"), "invalidated_at_bar": None},
    ])

    out = compute_structural_targets(trigger, zones)
    row = out.iloc[0]

    assert row["target_status"] == "no_opposing_zone"
    assert row["target_price"] is None
    assert row["structural_rr"] is None
    assert row["stop_price"] == 95.0  # stop/entry are still recorded even on skip

    print("  [+] no opposing zone ahead of price -> target_status=no_opposing_zone, target/rr=NULL")
    print("  [OK] test_no_opposing_zone_triggers_skip_fallback_not_a_default_ratio PASSED\n")


def test_opposing_zone_lookup_is_causal_no_lookahead():
    print("=" * 60)
    print("3. Opposing-zone lookup must be causal: a zone created AFTER")
    print("   confirmed_at_bar, or already invalidated by confirmed_at_bar,")
    print("   must be ignored even though it would produce a tighter")
    print("   (more attractive) R:R than the correct, causally-valid zone")
    print("=" * 60)

    trigger = _bullish_trigger(entry=100.0, own_zone_bottom=95.0, confirmed_at=CONFIRMED)
    zones = pd.DataFrame([
        # Tighter, more attractive near edge (102) -- but created AFTER
        # confirmed_at_bar. Must be excluded (would be lookahead).
        {"zone_type": "order_block_bearish", "zone_top": 106.0, "zone_bottom": 102.0,
         "created_at_bar": CONFIRMED + pd.Timedelta(hours=1), "invalidated_at_bar": None},
        # Tighter near edge (101) but created before confirmed_at_bar AND
        # already invalidated before confirmed_at_bar. Must be excluded.
        {"zone_type": "order_block_bearish", "zone_top": 103.0, "zone_bottom": 101.0,
         "created_at_bar": CONFIRMED - pd.Timedelta(hours=6),
         "invalidated_at_bar": CONFIRMED - pd.Timedelta(hours=1)},
        # The only causally-valid opposing zone: created before
        # confirmed_at_bar, never invalidated.
        {"zone_type": "order_block_bearish", "zone_top": 124.0, "zone_bottom": 120.0,
         "created_at_bar": CONFIRMED - pd.Timedelta(hours=6), "invalidated_at_bar": None},
    ])

    out = compute_structural_targets(trigger, zones)
    row = out.iloc[0]

    assert row["target_status"] == "structural"
    assert row["opposing_zone_bottom"] == 120.0, (
        f"must select the causally-valid zone (edge=120), not the future zone (102) "
        f"or the pre-invalidated zone (101) -- got edge={row['opposing_zone_bottom']}"
    )
    # reward_full = 120-100=20, reward=0.85*20=17, target=117
    assert abs(row["target_price"] - 117.0) < 1e-9

    print(f"  [+] correctly selected the causally-valid opposing zone (edge=120), not the future (102) or pre-invalidated (101) zone")
    print("  [OK] test_opposing_zone_lookup_is_causal_no_lookahead PASSED\n")


def test_near_zero_risk_flagged_stop_too_tight_not_blown_up_rr():
    print("=" * 60)
    print("4. Regression: when entry lands very close to the trigger zone's")
    print("   own far edge (stop), risk approaches zero and structural_rr")
    print("   would blow up independent of reward -- found via real data")
    print("   (3 outliers at R:R 92.7/80.9/65.4, all with risk < 0.35 price")
    print("   points). Must be flagged 'stop_too_tight' and skipped, NOT")
    print("   produce a numerically unstable R:R.")
    print("=" * 60)

    # Same shape as the real 92.7-R:R outlier: entry sits just 0.31 above
    # stop, while a genuine, far-away opposing zone exists (would produce
    # reward=~25.5 -- an enormous R:R if the floor didn't intervene).
    trigger = _bullish_trigger(entry=100.31, own_zone_bottom=100.0, atr_14=10.0)  # risk=0.31, min_risk=0.5*10=5.0
    zones = pd.DataFrame([{
        "zone_type": "order_block_bearish", "zone_top": 135.0, "zone_bottom": 130.0,
        "created_at_bar": pd.Timestamp("2026-01-01 06:00:00"), "invalidated_at_bar": None,
    }])

    out = compute_structural_targets(trigger, zones)
    row = out.iloc[0]

    assert row["target_status"] == "stop_too_tight", f"expected stop_too_tight, got {row['target_status']}"
    assert row["target_price"] is None, "a stop-too-tight trigger must not get a numerically unstable target"
    assert row["structural_rr"] is None, "a stop-too-tight trigger must not get a numerically unstable R:R"
    assert row["stop_price"] == 100.0  # entry/stop are still recorded for diagnosis

    print(f"  [+] risk=0.31 < min_risk=5.0 (0.5x atr_14=10) -> target_status=stop_too_tight, target/rr=NULL")

    # Regression: the same risk distance (0.31) with a smaller ATR (so
    # min_risk drops below it) must NOT be flagged -- the floor only fires
    # when risk is genuinely tight relative to the prevailing volatility,
    # not as a blanket threshold.
    trigger_ok = _bullish_trigger(entry=100.31, own_zone_bottom=100.0, atr_14=0.5)  # min_risk=0.25 < risk=0.31
    out_ok = compute_structural_targets(trigger_ok, zones)
    row_ok = out_ok.iloc[0]
    assert row_ok["target_status"] == "structural", (
        f"risk (0.31) above min_risk (0.25) must NOT be flagged, got {row_ok['target_status']}"
    )
    print(f"  [+] risk=0.31 >= min_risk=0.25 (0.5x atr_14=0.5) -> normal structural computation unaffected")

    print("  [OK] test_near_zero_risk_flagged_stop_too_tight_not_blown_up_rr PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   STRUCTURAL TP ENGINE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_clear_nearby_opposing_zone_produces_tight_structural_rr()
    test_no_opposing_zone_triggers_skip_fallback_not_a_default_ratio()
    test_opposing_zone_lookup_is_causal_no_lookahead()
    test_near_zero_risk_flagged_stop_too_tight_not_blown_up_rr()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
