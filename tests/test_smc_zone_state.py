"""
Unit tests for analysis.smc_crt.zone_state.SMCZoneStateEngine (Phase 2a).

Unlike test_all_analysis.py (smoke tests that just check the pipeline runs),
these hand-construct specific candle sequences with a known FVG / Order
Block / swing-resistance pattern baked in, and assert the exact zone
boundaries and active -> mitigated -> invalidated transitions the engine
should produce. BOS/CHoCH detection itself (structure.py) is pre-existing,
already-used code — it's exercised here only as a precondition for Order
Block anchoring, not re-tested for its own sake.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.smc_crt.zone_state import SMCZoneStateEngine, FVG_INVALIDATION_PCT  # noqa: E402


def _df(rows):
    n = len(rows)
    dt = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame({
        "price_datetime": dt,
        "open_price":  [r[0] for r in rows],
        "high_price":  [r[1] for r in rows],
        "low_price":   [r[2] for r in rows],
        "close_price": [r[3] for r in rows],
    })


def test_fvg_lifecycle():
    print("=" * 60)
    print("1. FVG: detection + mitigated -> invalidated lifecycle")
    print("=" * 60)

    rows = [
        (100.0, 101.0,  99.0, 100.5),   # 0
        (101.0, 103.0, 100.2, 102.8),   # 1
        (103.0, 104.0, 102.5, 103.5),   # 2  bullish FVG: bottom=high[0]=101, top=low[2]=102.5
        (103.5, 104.0, 102.6, 103.8),   # 3  no touch -> stays active
        (103.8, 104.0, 102.0, 102.2),   # 4  wick into gap, close above midpoint -> mitigated
        (102.2, 102.3, 100.5, 101.0),   # 5  close below midpoint (101.75) -> invalidated
    ]
    df = _df(rows)
    engine = SMCZoneStateEngine(pivot_window=1)
    zones = engine.detect_zones(df, symbol="TEST", timeframe="h1")

    fvgs = zones[zones["zone_type"] == "fvg_bullish"]
    assert len(fvgs) == 1, f"expected exactly 1 bullish FVG, got {len(fvgs)}"
    z = fvgs.iloc[0]

    assert z["zone_bottom"] == 101.0, z["zone_bottom"]
    assert z["zone_top"] == 102.5, z["zone_top"]
    assert z["created_at_bar"] == df["price_datetime"].iloc[2]
    assert FVG_INVALIDATION_PCT == 0.5

    assert z["state"] == "invalidated", z["state"]
    assert z["mitigated_at_bar"] == df["price_datetime"].iloc[4]
    assert z["invalidated_at_bar"] == df["price_datetime"].iloc[5]

    print(f"  [+] FVG zone: bottom={z['zone_bottom']} top={z['zone_top']}")
    print(f"  [+] mitigated_at={z['mitigated_at_bar']}  invalidated_at={z['invalidated_at_bar']}")
    print("  [OK] test_fvg_lifecycle PASSED\n")


def test_order_block_lifecycle():
    print("=" * 60)
    print("2. Order Block: BOS-anchored detection + mitigated -> invalidated")
    print("=" * 60)

    rows = [
        (100.0, 102.0,  99.0, 101.0),   # 0
        (101.0, 108.0, 100.0, 107.0),   # 1  swing-high pivot (H=108)
        (107.0, 104.0, 103.0, 103.5),   # 2  confirms swing high (w=1) -> sh=108
        (103.5, 104.0, 100.0, 100.5),   # 3  bearish, not the nearest one to the BOS
        (100.5, 110.0, 100.0, 109.0),   # 4  close(109) > sh(108), but trend was NEUTRAL -> no signal yet, trend->BULLISH
        (109.0, 111.0, 107.0, 108.0),   # 5  new swing-high pivot (H=111)
        (108.0, 109.0, 105.0, 106.0),   # 6  confirms swing high -> sh=111
        (106.0, 107.0, 103.0, 104.0),   # 7  bearish candle -> becomes the Order Block
        (104.0, 113.0, 104.0, 112.0),   # 8  close(112) > sh(111), trend already BULLISH -> would BOS, but no swing-low yet this early bar; see below
        (112.0, 114.0, 110.0, 113.0),   # 9  close(113) > sh(111), trend BULLISH -> BULLISH_BOS fires here
        (113.0, 113.0, 105.0, 106.0),   # 10 wick into OB [103,107] -> mitigated
        (106.0, 107.0, 101.0, 102.0),   # 11 close(102) < bottom(103) -> invalidated
    ]
    df = _df(rows)
    engine = SMCZoneStateEngine(pivot_window=1)
    zones = engine.detect_zones(df, symbol="TEST", timeframe="h1")

    obs = zones[zones["zone_type"] == "order_block_bullish"]
    assert len(obs) == 1, f"expected exactly 1 bullish OB, got {len(obs)}\n{obs}"
    z = obs.iloc[0]

    assert z["created_at_bar"] == df["price_datetime"].iloc[7], "OB should anchor to the bearish candle at bar 7"
    assert z["zone_top"] == 107.0
    assert z["zone_bottom"] == 103.0

    assert z["state"] == "invalidated", z["state"]
    assert z["mitigated_at_bar"] == df["price_datetime"].iloc[8], \
        "bar 8 already wicks into [103,107] (low=104), so mitigation fires immediately"
    assert z["invalidated_at_bar"] == df["price_datetime"].iloc[11]

    print(f"  [+] OB zone: bottom={z['zone_bottom']} top={z['zone_top']} created_at={z['created_at_bar']}")
    print(f"  [+] mitigated_at={z['mitigated_at_bar']}  invalidated_at={z['invalidated_at_bar']}")
    print("  [OK] test_order_block_lifecycle PASSED\n")


def test_swing_resistance_requires_confirmed_close():
    print("=" * 60)
    print("3. Swing resistance: single-bar spike does NOT invalidate; two")
    print("   consecutive closes beyond the zone DOES")
    print("=" * 60)

    rows = [
        (100.0, 101.0,  99.0, 100.0),   # 0
        (100.0, 105.0, 104.0, 104.5),   # 1  swing-high pivot -> zone [104,105]
        (104.5, 103.0, 102.0, 102.5),   # 2  confirms the pivot
        (102.5, 106.0, 102.0, 106.2),   # 3  close(106.2) > top(105): breach #1, but wick also touches zone -> mitigated
        (106.0, 106.0, 103.0, 104.5),   # 4  close back below top -> breach #1 NOT confirmed (reclaimed)
        (104.5, 107.0, 104.0, 105.5),   # 5  close(105.5) > top(105): breach #2 begins
        (105.5, 108.0, 105.0, 106.5),   # 6  close(106.5) > top(105) again -> CONFIRMED -> invalidated here
    ]
    df = _df(rows)
    engine = SMCZoneStateEngine(pivot_window=1)
    zones = engine.detect_zones(df, symbol="TEST", timeframe="h1")

    res_zones = zones[
        (zones["zone_type"] == "swing_resistance") &
        (zones["created_at_bar"] == df["price_datetime"].iloc[1])
    ]
    assert len(res_zones) == 1, f"expected exactly 1 matching resistance zone, got {len(res_zones)}"
    z = res_zones.iloc[0]

    assert z["zone_top"] == 105.0
    assert z["zone_bottom"] == 104.0
    assert z["mitigated_at_bar"] == df["price_datetime"].iloc[3], \
        "bar 3's spike-and-wick should register as a mitigation touch"
    assert z["state"] == "invalidated", \
        f"expected invalidated after the 2-consecutive-close confirmation at bar 6, got {z['state']}"
    assert z["invalidated_at_bar"] == df["price_datetime"].iloc[6], \
        "bar 3's single-bar spike (reclaimed at bar 4) must NOT be the invalidation point"

    print(f"  [+] Resistance zone: bottom={z['zone_bottom']} top={z['zone_top']}")
    print(f"  [+] mitigated_at={z['mitigated_at_bar']}  invalidated_at={z['invalidated_at_bar']}")
    print("  [OK] test_swing_resistance_requires_confirmed_close PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   SMC ZONE-STATE ENGINE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_fvg_lifecycle()
    test_order_block_lifecycle()
    test_swing_resistance_requires_confirmed_close()

    print("#" * 60)
    print("   ALL ZONE-STATE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
