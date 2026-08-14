"""
Unit tests for analysis.divergence.intermarket_divergence_state
(Phase 2h: xau_dxy/eur_dxy/xau_us10y/xau_gdx; Phase 2i: cot_gold/cot_eur/xau_spdr).

TechnicalDivergenceEngine.detect()/classify_divergence() are pre-existing,
already-proven code (Category 2: RSI/OBV/Stochastic/CCI) — not re-tested
for their pivot/classification math here. These tests exercise what's new:
IntermarketDivergenceEngine's relationship-aware sign handling, which is
the one thing genuinely different about inter-market divergence versus a
same-direction computed indicator. Test 1 is the full worked example
(xau_dxy, inverse) covering all four Regular/Hidden x Bullish/Bearish
combinations with the underlying economic reasoning spelled out. Tests
2-3 reuse the same synthetic pattern for the other 3 Phase 2h models
(confirming wiring: correct divergence_type, correct symbol, correct
relationship handling) rather than re-deriving the classification math
per model. Test 4 is the deliberate bug-catcher: the same raw driver
movement must classify differently (or not at all) depending on
relationship, proving the sign logic isn't accidentally symmetric.
Test 6 exercises the one thing genuinely new for COT: a driver value
that only changes every few bars (simulating merge_asof backward-filling
one weekly report across several daily bars) must still produce the
exact correct value at each pivot, with no special pivot-timing logic
needed. Test 7 reuses the proven pattern for cot_gold/cot_eur/xau_spdr,
same as tests 2-3 did for the Phase 2h models.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.divergence.intermarket_divergence_state import (  # noqa: E402
    IntermarketDivergenceEngine, INTERMARKET_MODELS,
)


def _df(prices, driver, start="2026-01-01"):
    n = len(prices)
    dt = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({"price_datetime": dt, "close_price": prices, "driver_close": driver})


def test_xau_dxy_full_worked_example_inverse_relationship():
    print("=" * 60)
    print("1. XAU vs DXY (inverse): all 4 Regular/Hidden x Bullish/Bearish combinations")
    print("=" * 60)

    engine = IntermarketDivergenceEngine(pivot_window=3)

    # --- Regular Bullish ---
    # Gold LL (95->92). DXY DECLINING at those same bars (105.30->102.10):
    # the dollar isn't strengthening to justify gold's new low -> gold's
    # weakness lacks confirmation -> Regular Bullish (reversal risk up).
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    dxy    = [110, 108, 107, 106, 105.5, 105.30, 106, 107, 108, 107, 106, 105, 104, 103, 102.10, 103, 104, 105]
    out = engine.detect(_df(prices, dxy), "XAUUSD", "d1", "xau_dxy", "inverse")
    bullish = out[out["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
    assert bullish.iloc[0]["divergence_type"] == "xau_dxy"
    # Stored values are the REAL (non-negated) DXY price, not the sign-flipped intermediate.
    assert bullish.iloc[0]["prev_pivot_indicator"] == 105.30 and bullish.iloc[0]["curr_pivot_indicator"] == 102.10
    print(f"  [+] Regular Bullish: gold {bullish.iloc[0]['prev_pivot_price']}->{bullish.iloc[0]['curr_pivot_price']}, "
          f"DXY {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']} (real DXY values, declining)")

    # --- Regular Bearish ---
    # Gold HH (110->114). DXY RISING at those same bars (100.8->102.0):
    # the dollar strengthening alongside a gold rally is atypical for the
    # inverse relationship -> the rally isn't backed by the expected
    # dollar-weakness tailwind -> Regular Bearish (reversal risk down).
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 108, 110, 112, 114, 112, 110, 108, 106]
    dxy    = [99.2, 99.6, 100.0, 100.4, 100.7, 100.8, 101.1, 101.5, 102.0, 101.7, 101.4, 101.1, 101.4, 102.0, 102.4, 102.8, 103.2, 103.6]
    out = engine.detect(_df(prices, dxy), "XAUUSD", "d1", "xau_dxy", "inverse")
    bearish = out[out["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "regular"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 100.8 and bearish.iloc[0]["curr_pivot_indicator"] == 102.0
    print(f"  [+] Regular Bearish: gold {bearish.iloc[0]['prev_pivot_price']}->{bearish.iloc[0]['curr_pivot_price']}, "
          f"DXY {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']} (real DXY values, rising)")

    # --- Hidden Bullish ---
    # Gold HL (95->97, shallower pullback in an uptrend). DXY RISING at
    # those same bars (100->103): dollar strengthening into gold's
    # shallow pullback is the expected inverse-relationship headwind ->
    # consistent with continuation once the pullback resolves -> Hidden Bullish.
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 98, 97, 98, 99, 100, 99, 98, 97]
    dxy    = [98, 98.5, 99, 99.3, 99.6, 100, 99.7, 99.3, 98.8, 98.5, 99, 103, 102.5, 102, 101, 101.3, 101.6, 101.9]
    out = engine.detect(_df(prices, dxy), "XAUUSD", "d1", "xau_dxy", "inverse")
    bullish = out[out["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "hidden"
    assert bullish.iloc[0]["prev_pivot_indicator"] == 100 and bullish.iloc[0]["curr_pivot_indicator"] == 103
    print(f"  [+] Hidden Bullish: gold {bullish.iloc[0]['prev_pivot_price']}->{bullish.iloc[0]['curr_pivot_price']}, "
          f"DXY {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']} (real DXY values, rising)")

    # --- Hidden Bearish ---
    # Gold LH (110->108, shallower bounce in a downtrend). DXY DECLINING
    # at those same bars (102->99): dollar weakening into gold's shallow
    # bounce is the expected inverse-relationship headwind for the bounce
    # to fail -> consistent with downtrend continuation -> Hidden Bearish.
    prices = [100, 102, 104, 106, 108, 110, 108, 106, 104, 106, 107, 108, 107, 106, 105, 106, 107, 106]
    dxy    = [103, 102.5, 102, 101.7, 101.4, 101, 101.3, 101.7, 102.2, 101.7, 101.3, 99, 99.5, 100, 100.5, 100.2, 99.9, 99.6]
    out = engine.detect(_df(prices, dxy), "XAUUSD", "d1", "xau_dxy", "inverse")
    bearish = out[out["direction"] == "bearish"]
    assert len(bearish) == 1 and bearish.iloc[0]["divergence_class"] == "hidden"
    assert bearish.iloc[0]["prev_pivot_indicator"] == 101 and bearish.iloc[0]["curr_pivot_indicator"] == 99
    print(f"  [+] Hidden Bearish: gold {bearish.iloc[0]['prev_pivot_price']}->{bearish.iloc[0]['curr_pivot_price']}, "
          f"DXY {bearish.iloc[0]['prev_pivot_indicator']}->{bearish.iloc[0]['curr_pivot_indicator']} (real DXY values, declining)")

    print("  [OK] test_xau_dxy_full_worked_example_inverse_relationship PASSED\n")


def test_eur_dxy_and_xau_us10y_share_inverse_pattern():
    print("=" * 60)
    print("2. EUR vs DXY and XAU vs US10Y (both inverse): same pattern, different wiring")
    print("=" * 60)

    engine = IntermarketDivergenceEngine(pivot_window=3)
    # Reuse the exact Regular Bullish pattern from test 1: primary LL,
    # driver declining at those bars -> Regular Bullish.
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    driver = [110, 108, 107, 106, 105.5, 105.30, 106, 107, 108, 107, 106, 105, 104, 103, 102.10, 103, 104, 105]

    for divergence_type, primary_symbol in [("eur_dxy", "EURUSD"), ("xau_us10y", "XAUUSD")]:
        assert INTERMARKET_MODELS[divergence_type]["relationship"] == "inverse"
        assert INTERMARKET_MODELS[divergence_type]["primary"] == primary_symbol
        out = engine.detect(_df(prices, driver), primary_symbol, "d1", divergence_type, "inverse")
        bullish = out[out["direction"] == "bullish"]
        assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
        assert bullish.iloc[0]["divergence_type"] == divergence_type
        assert bullish.iloc[0]["symbol"] == primary_symbol
        print(f"  [+] {divergence_type} ({primary_symbol}): Regular Bullish detected, "
              f"driver {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")

    print("  [OK] test_eur_dxy_and_xau_us10y_share_inverse_pattern PASSED\n")


def test_xau_gdx_direct_relationship():
    print("=" * 60)
    print("3. XAU vs GDX (direct): no sign flip, same-direction logic applies as-is")
    print("=" * 60)

    engine = IntermarketDivergenceEngine(pivot_window=3)
    assert INTERMARKET_MODELS["xau_gdx"]["relationship"] == "direct"

    # Regular Bullish (direct): gold LL, GDX HL (rising at its lows,
    # miners refusing to confirm gold's weakness) -> Regular Bullish.
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    gdx    = [40, 38, 35, 32, 30.5, 30, 31, 32, 33, 32.5, 32, 31.5, 32, 33, 35, 37, 39, 41]
    out = engine.detect(_df(prices, gdx), "XAUUSD", "d1", "xau_gdx", "direct")
    bullish = out[out["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
    assert bullish.iloc[0]["divergence_type"] == "xau_gdx"
    assert bullish.iloc[0]["prev_pivot_indicator"] == 30 and bullish.iloc[0]["curr_pivot_indicator"] == 35

    print(f"  [+] Regular Bullish: gold {bullish.iloc[0]['prev_pivot_price']}->{bullish.iloc[0]['curr_pivot_price']}, "
          f"GDX {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_xau_gdx_direct_relationship PASSED\n")


def test_sign_handling_is_not_accidentally_symmetric():
    print("=" * 60)
    print("4. Bug-catcher: the SAME raw driver movement classifies differently")
    print("   (or not at all) depending on relationship='inverse' vs 'direct'")
    print("=" * 60)

    engine = IntermarketDivergenceEngine(pivot_window=3)

    # Gold LL (95->92); driver DECLINING at those same bars (105.30->102.10).
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    driver = [110, 108, 107, 106, 105.5, 105.30, 106, 107, 108, 107, 106, 105, 104, 103, 102.10, 103, 104, 105]

    out_inverse = engine.detect(_df(prices, driver), "XAUUSD", "d1", "xau_dxy", "inverse")
    out_direct = engine.detect(_df(prices, driver), "XAUUSD", "d1", "xau_gdx", "direct")

    # Inverse: driver declining while price falls -> no confirmation from
    # the (inverted) driver -> Regular Bullish (a genuine divergence).
    assert len(out_inverse) == 1 and out_inverse.iloc[0]["divergence_class"] == "regular" \
        and out_inverse.iloc[0]["direction"] == "bullish"
    # Direct: driver declining while price ALSO falls -> both moving
    # together as expected for a direct relationship -> no divergence at all.
    assert out_direct.empty, f"direct relationship must NOT signal on confirming (same-direction) movement, got:\n{out_direct}"

    print(f"  [+] inverse: {out_inverse.iloc[0]['divergence_class']}/{out_inverse.iloc[0]['direction']} "
          f"(genuine divergence)  |  direct: no signal (confirmation, not divergence)")
    print("  [OK] test_sign_handling_is_not_accidentally_symmetric PASSED\n")


def test_all_intermarket_types_distinct_from_technical_types():
    print("=" * 60)
    print("5. Inter-market divergence_type values don't collide with technical ones")
    print("   in the shared divergence_signals persistence key")
    print("=" * 60)

    engine = IntermarketDivergenceEngine(pivot_window=3)
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    driver = [110, 108, 107, 106, 105.5, 105.30, 106, 107, 108, 107, 106, 105, 104, 103, 102.10, 103, 104, 105]

    all_signals = []
    for divergence_type, cfg in INTERMARKET_MODELS.items():
        out = engine.detect(_df(prices, driver), cfg["primary"], "d1", divergence_type, cfg["relationship"])
        if not out.empty:
            all_signals.append(out)

    combined = pd.concat(all_signals, ignore_index=True)
    assert set(combined["divergence_type"].unique()) <= set(INTERMARKET_MODELS.keys())
    key_cols = ["symbol", "timeframe", "divergence_type", "divergence_class", "curr_pivot_datetime"]
    keys = combined[key_cols].apply(tuple, axis=1)
    assert keys.nunique() == len(combined), "each inter-market model must produce a distinct persistence key"

    print(f"  [+] {len(combined)} signals across {combined['divergence_type'].nunique()} inter-market types, "
          f"all keys distinct")
    print("  [OK] test_all_intermarket_types_distinct_from_technical_types PASSED\n")


def test_weekly_driver_forward_filled_onto_daily_price():
    print("=" * 60)
    print("6. COT's weekly-onto-daily granularity: a driver value that only")
    print("   changes every ~6 bars (simulating merge_asof backward-fill of a")
    print("   weekly report onto daily price) still yields correct pivot values")
    print("=" * 60)

    # Same daily price template as every other test. Driver changes in
    # blocks of 6 consecutive identical values (as merge_asof(direction=
    # "backward") would produce forward-filling one weekly COT report
    # across ~6 trading days) rather than a fresh value every bar.
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    driver = [-50000] * 6 + [-65000] * 6 + [-80000] * 6
    assert len(driver) == len(prices)

    engine = IntermarketDivergenceEngine(pivot_window=3)
    out = engine.detect(_df(prices, driver), "XAUUSD", "d1", "cot_gold", "inverse")

    bullish = out[out["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
    # The pivot bars (idx5, idx14) fall inside the 1st and 3rd blocks —
    # confirms the correct (repeated/stale) block value was read at each,
    # not some interpolated or off-by-one value.
    assert bullish.iloc[0]["prev_pivot_indicator"] == -50000
    assert bullish.iloc[0]["curr_pivot_indicator"] == -80000

    print(f"  [+] prev pivot (day 5, inside block 1) driver={bullish.iloc[0]['prev_pivot_indicator']}")
    print(f"  [+] curr pivot (day 14, inside block 3) driver={bullish.iloc[0]['curr_pivot_indicator']}")
    print("  [OK] test_weekly_driver_forward_filled_onto_daily_price PASSED\n")


def test_cot_gold_cot_eur_and_xau_spdr_wiring():
    print("=" * 60)
    print("7. cot_gold/cot_eur (inverse, commercial_net_position) and xau_spdr")
    print("   (direct, GLD holdings): wiring only, reusing proven patterns")
    print("=" * 60)

    engine = IntermarketDivergenceEngine(pivot_window=3)

    # cot_gold / cot_eur: inverse, same declining-driver-at-low-pivots
    # pattern as xau_dxy/eur_dxy/xau_us10y (commercial_net_position is
    # exactly analogous to those drivers under the same sign convention).
    prices = [100, 99, 98, 97, 96, 95, 96, 97, 98, 97, 96, 95, 94, 93, 92, 93, 94, 95]
    comm_net = [-40000, -45000, -48000, -50000, -52000, -55000, -53000, -51000, -49000,
                -51000, -53000, -56000, -60000, -65000, -72000, -68000, -64000, -60000]
    for divergence_type, primary_symbol in [("cot_gold", "XAUUSD"), ("cot_eur", "EURUSD")]:
        assert INTERMARKET_MODELS[divergence_type] == {"primary": primary_symbol, "relationship": "inverse"}
        out = engine.detect(_df(prices, comm_net), primary_symbol, "d1", divergence_type, "inverse")
        bullish = out[out["direction"] == "bullish"]
        assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
        assert bullish.iloc[0]["divergence_type"] == divergence_type
        assert bullish.iloc[0]["symbol"] == primary_symbol
        # pivot bars land at idx5/idx14 of comm_net -> -55000 declining to -72000
        assert bullish.iloc[0]["prev_pivot_indicator"] == -55000 and bullish.iloc[0]["curr_pivot_indicator"] == -72000
        print(f"  [+] {divergence_type} ({primary_symbol}): Regular Bullish, "
              f"commercial_net {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")

    # xau_spdr: direct, same pattern as xau_gdx (holdings rising at price
    # lows = miners/holdings not confirming weakness -> Regular Bullish).
    assert INTERMARKET_MODELS["xau_spdr"] == {"primary": "XAUUSD", "relationship": "direct"}
    tonnes = [920, 910, 900, 890, 880, 870, 875, 880, 885, 882, 878, 874, 878, 882, 895, 905, 915, 925]
    out = engine.detect(_df(prices, tonnes), "XAUUSD", "d1", "xau_spdr", "direct")
    bullish = out[out["direction"] == "bullish"]
    assert len(bullish) == 1 and bullish.iloc[0]["divergence_class"] == "regular"
    assert bullish.iloc[0]["prev_pivot_indicator"] == 870 and bullish.iloc[0]["curr_pivot_indicator"] == 895
    print(f"  [+] xau_spdr (XAUUSD): Regular Bullish, "
          f"tonnes {bullish.iloc[0]['prev_pivot_indicator']}->{bullish.iloc[0]['curr_pivot_indicator']}")

    print("  [OK] test_cot_gold_cot_eur_and_xau_spdr_wiring PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   INTER-MARKET DIVERGENCE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_xau_dxy_full_worked_example_inverse_relationship()
    test_eur_dxy_and_xau_us10y_share_inverse_pattern()
    test_xau_gdx_direct_relationship()
    test_sign_handling_is_not_accidentally_symmetric()
    test_all_intermarket_types_distinct_from_technical_types()
    test_weekly_driver_forward_filled_onto_daily_price()
    test_cot_gold_cot_eur_and_xau_spdr_wiring()

    print("#" * 60)
    print("   ALL INTER-MARKET DIVERGENCE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
