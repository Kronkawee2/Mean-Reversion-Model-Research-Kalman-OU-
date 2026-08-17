"""
Unit tests for analysis.strategies.confluence_zone_engine (hand-constructed
scenarios, same style as test_smc_zone_state.py -- exact boundary/count
assertions on a known candle sequence, not just a smoke test).
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.strategies.confluence_zone_engine import (  # noqa: E402
    detect_confluence_zones, _cluster_events, _core_range, _price_overlap,
    CONFLUENCE_MAX_SPAN_BARS,
)


def _df(rows, freq="4h"):
    n = len(rows)
    dt = pd.date_range("2026-01-01", periods=n, freq=freq)
    return pd.DataFrame({
        "price_datetime": dt,
        "open_price":  [r[0] for r in rows],
        "high_price":  [r[1] for r in rows],
        "low_price":   [r[2] for r in rows],
        "close_price": [r[3] for r in rows],
    })


def test_price_overlap():
    print("=" * 60)
    print("1. _price_overlap helper")
    print("=" * 60)
    a = {"lo": 100.0, "hi": 110.0}
    b = {"lo": 105.0, "hi": 120.0}
    c = {"lo": 111.0, "hi": 120.0}
    assert _price_overlap(a, b) is True, "overlapping ranges must return True"
    assert _price_overlap(a, c) is False, "non-overlapping ranges must return False"
    print("  [OK] test_price_overlap PASSED\n")


def test_cluster_merges_overlapping_same_direction_within_window():
    print("=" * 60)
    print("2. clustering: overlapping same-direction factors within the time window merge")
    print("=" * 60)
    t0 = pd.Timestamp("2026-01-01 00:00")
    events = [
        dict(ts=t0, direction="bullish", lo=100.0, hi=110.0, factor="FVG", detail={}),
        dict(ts=t0 + pd.Timedelta(hours=8), direction="bullish", lo=105.0, hi=115.0, factor="OB", detail={}),
        # different direction, must NOT merge even though price overlaps
        dict(ts=t0 + pd.Timedelta(hours=8), direction="bearish", lo=105.0, hi=115.0, factor="OB", detail={}),
        # same direction, overlapping price, but too far in time -> separate cluster
        dict(ts=t0 + pd.Timedelta(days=30), direction="bullish", lo=106.0, hi=112.0, factor="SwingSR", detail={}),
    ]
    clusters = _cluster_events(events, pd.Timedelta(hours=20), pd.Timedelta(days=99999))
    bullish_clusters = [c for c in clusters if c["direction"] == "bullish"]
    assert len(bullish_clusters) == 2, f"expected 2 bullish clusters (one merged FVG+OB, one lone late SwingSR), got {len(bullish_clusters)}"
    merged = [c for c in bullish_clusters if len(c["factor_set"]) == 2][0]
    assert merged["factor_set"] == {"FVG", "OB"}
    assert merged["lo"] == 100.0 and merged["hi"] == 115.0, "merged cluster must be the UNION of both factors' ranges"
    bearish_clusters = [c for c in clusters if c["direction"] == "bearish"]
    assert len(bearish_clusters) == 1, "opposite-direction factor at the same price/time must not merge into the bullish cluster"
    print(f"  [+] merged bullish cluster: factors={merged['factor_set']} range=[{merged['lo']}, {merged['hi']}]")
    print("  [OK] test_cluster_merges_overlapping_same_direction_within_window PASSED\n")


def test_span_cap_splits_a_long_chain_even_when_every_gap_is_tight():
    print("=" * 60)
    print("3. CONFLUENCE_MAX_SPAN_BARS splits a drifting chain even though every individual gap is inside the gap window")
    print("=" * 60)
    t0 = pd.Timestamp("2026-01-01 00:00")
    gap = pd.Timedelta(hours=4)          # well inside a 20h gap window
    bar_delta = pd.Timedelta(hours=20)
    span_delta = pd.Timedelta(hours=4 * CONFLUENCE_MAX_SPAN_BARS)

    # a chain of same-direction, overlapping-price events spaced 4h apart,
    # long enough that the chain's total span exceeds span_delta even
    # though no single link ever violates bar_delta.
    n_events = CONFLUENCE_MAX_SPAN_BARS + 5
    events = [dict(ts=t0 + i * gap, direction="bullish", lo=100.0, hi=101.0, factor="Sweep", detail={})
              for i in range(n_events)]

    uncapped = _cluster_events(events, bar_delta, pd.Timedelta(days=99999))
    capped = _cluster_events(events, bar_delta, span_delta)

    assert len(uncapped) == 1, "without a span cap the whole tight chain must merge into one cluster"
    assert len(capped) >= 2, "with the span cap, a chain exceeding CONFLUENCE_MAX_SPAN_BARS in total length must split"
    for c in capped:
        span_hours = (c["last_ts"] - c["first_ts"]).total_seconds() / 3600
        assert span_hours <= 4 * CONFLUENCE_MAX_SPAN_BARS, f"no capped cluster may span more than {4 * CONFLUENCE_MAX_SPAN_BARS}h, got {span_hours}h"
    print(f"  [+] uncapped: 1 cluster spanning {(uncapped[0]['last_ts'] - uncapped[0]['first_ts']).total_seconds() / 3600:.0f}h")
    print(f"  [+] capped:   {len(capped)} clusters, each <= {4 * CONFLUENCE_MAX_SPAN_BARS}h")
    print("  [OK] test_span_cap_splits_a_long_chain_even_when_every_gap_is_tight PASSED\n")


def test_core_range_is_intersection_of_ranged_factors_only():
    print("=" * 60)
    print("4. zone_core_range = intersection of RANGED factors, point events excluded")
    print("=" * 60)
    cluster = dict(
        direction="bullish", lo=100.0, hi=130.0,
        members=[
            dict(factor="FVG", lo=100.0, hi=120.0, ts=None),
            dict(factor="OB", lo=110.0, hi=130.0, ts=None),
            dict(factor="CHoCH", lo=115.0, hi=115.0, ts=None),  # point event, must not affect core intersection
        ],
    )
    core_lo, core_hi = _core_range(cluster)
    assert (core_lo, core_hi) == (110.0, 120.0), f"expected intersection [110,120] of the two ranged factors, got [{core_lo},{core_hi}]"
    print(f"  [+] core range: [{core_lo}, {core_hi}]  (full range was [100, 130])")

    # fewer than 2 ranged factors -> falls back to full range
    cluster2 = dict(direction="bullish", lo=100.0, hi=100.0,
                     members=[dict(factor="CHoCH", lo=100.0, hi=100.0, ts=None),
                              dict(factor="Sweep", lo=100.0, hi=100.0, ts=None)])
    core_lo2, core_hi2 = _core_range(cluster2)
    assert (core_lo2, core_hi2) == (cluster2["lo"], cluster2["hi"]), "with <2 ranged factors, core must fall back to full range"
    print(f"  [+] point-only cluster core falls back to full range: [{core_lo2}, {core_hi2}]")
    print("  [OK] test_core_range_is_intersection_of_ranged_factors_only PASSED\n")


# Shared scenario: a clean downtrend (swing high at 103, swing low at 88)
# followed by a violent bullish break. This produces, on the real engines
# (not mocked): a bullish Order Block (the last bearish candle before the
# break), a swing-support zone, a liquidity sweep, a BULLISH_CHOCH, and a
# bullish FVG two candles later -- a genuine 4-factor confluence cluster,
# plus a separate, unrelated 2-factor bearish cluster earlier in the same
# data (SwingSR+FVG resistance around the initial down-leg).
_TREND_REVERSAL_ROWS = [
    (100.0, 101.0, 99.0, 100.5),
    (100.5, 102.0, 100.0, 101.5),
    (101.5, 103.0, 101.0, 102.5),   # swing high pivot (103)
    (102.5, 103.0, 97.0, 97.5),
    (97.5, 98.0, 94.0, 94.5),
    (94.5, 95.0, 90.0, 90.5),
    (90.5, 93.0, 90.0, 92.5),
    (92.5, 94.0, 91.0, 93.5),
    (93.5, 95.0, 92.0, 94.5),       # swing low pivot (88, set two rows down) confirmed here
    (94.5, 95.0, 88.0, 89.0),       # bearish -- becomes the bullish Order Block; close below 90 sets BEARISH trend
    (89.0, 91.0, 88.0, 90.5),
    (90.5, 93.0, 89.0, 91.5),
    (91.5, 95.0, 90.0, 93.5),
    (93.5, 115.0, 92.0, 114.0),     # break above 103 while BEARISH -> BULLISH_CHOCH
    (114.0, 118.0, 113.5, 117.0),
    (117.0, 122.0, 116.5, 121.0),   # gap vs candle 13's high (115) -> bullish FVG
]


def test_mode_a_2factor_qualifies_a_real_reversal_cluster():
    print("=" * 60)
    print("5. mode_a_2factor: a real OB+FVG+SwingSR+Sweep bullish reversal qualifies")
    print("=" * 60)
    df = _df(_TREND_REVERSAL_ROWS)
    zones = detect_confluence_zones(df, symbol="TEST", timeframe="h4", mode="mode_a_2factor")
    bullish = zones[zones["direction"] == "bullish"]
    assert len(bullish) >= 1, "expected at least one qualifying bullish confluence zone"
    z = bullish.iloc[0]
    assert z["factor_count"] >= 2
    assert z["mode"] == "mode_a_2factor"
    assert z["status"] == "active"
    print(f"  [+] zone: factors={[f['factor_type'] for f in z['factors']]}  "
          f"core=[{z['zone_core_bottom']}, {z['zone_core_top']}]  full=[{z['zone_full_bottom']}, {z['zone_full_top']}]  "
          f"confidence={z['confidence_score']}")
    print("  [OK] test_mode_a_2factor_qualifies_a_real_reversal_cluster PASSED\n")


def test_mode_b_3factor_is_stricter_than_mode_a():
    print("=" * 60)
    print("6. mode_b_3factor rejects the 2-factor bearish cluster that mode_a accepts")
    print("=" * 60)
    df = _df(_TREND_REVERSAL_ROWS)
    zones_a = detect_confluence_zones(df, symbol="TEST", timeframe="h4", mode="mode_a_2factor")
    zones_b = detect_confluence_zones(df, symbol="TEST", timeframe="h4", mode="mode_b_3factor")
    assert len(zones_a) > len(zones_b), "mode_b (stricter) must reject the weaker bearish cluster mode_a accepts"
    assert (zones_b["factor_count"] >= 3).all(), "every mode_b zone must have at least 3 contributing factors"
    print(f"  [+] mode_a zones: {len(zones_a)}   mode_b zones: {len(zones_b)}")
    print("  [OK] test_mode_b_3factor_is_stricter_than_mode_a PASSED\n")


def test_invalidation_on_adverse_close_through_full_range():
    print("=" * 60)
    print("7. status flips to 'invalidated' when price closes through zone_full_range adversely")
    print("=" * 60)
    rows = _TREND_REVERSAL_ROWS + [
        (121.0, 121.5, 80.0, 81.0),   # sharp reversal: closes well below the bullish zone's full range (88)
    ]
    df = _df(rows)
    zones = detect_confluence_zones(df, symbol="TEST", timeframe="h4", mode="mode_a_2factor")
    bullish = zones[zones["direction"] == "bullish"]
    assert len(bullish) >= 1
    z = bullish.iloc[0]
    assert z["status"] == "invalidated", f"expected invalidated after the close at 81.0 broke below zone_full_bottom={z['zone_full_bottom']}"
    assert z["resolved_at_bar"] == df["price_datetime"].iloc[-1]
    print(f"  [+] zone invalidated at {z['resolved_at_bar']}  (full_bottom was {z['zone_full_bottom']})")
    print("  [OK] test_invalidation_on_adverse_close_through_full_range PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   CONFLUENCE ZONE ENGINE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_price_overlap()
    test_cluster_merges_overlapping_same_direction_within_window()
    test_span_cap_splits_a_long_chain_even_when_every_gap_is_tight()
    test_core_range_is_intersection_of_ranged_factors_only()
    test_mode_a_2factor_qualifies_a_real_reversal_cluster()
    test_mode_b_3factor_is_stricter_than_mode_a()
    test_invalidation_on_adverse_close_through_full_range()

    print("#" * 60)
    print("   ALL CONFLUENCE ZONE ENGINE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
