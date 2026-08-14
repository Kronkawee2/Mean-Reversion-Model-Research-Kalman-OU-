"""
Unit tests for LiquiditySweepStateEngine (analysis/smc_crt/liquidity_state.py).
Hand-constructed OHLC sequences with a known, hand-verified swing pivot and
a known sweep bar, run directly with `python tests/test_liquidity_sweep_engine.py`
(no pytest available in this environment; matches test_htf_bias_engine.py's
style).
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.smc_crt.liquidity_state import LiquiditySweepStateEngine  # noqa: E402

PW = 3  # SMCStructureEngine's default pivot_window


def _bars(highs, lows, closes, start="2026-01-01 00:00"):
    dt = pd.date_range(start, periods=len(highs), freq="h")
    return pd.DataFrame({
        "price_datetime": dt,
        "high_price": highs,
        "low_price": lows,
        "close_price": closes,
    })


def test_bsl_sweep_detected_and_capped_to_swing_high():
    """
    Bars 0-6: high_price = [100,101,102,110,103,102,101] -> bar 3 (high=110)
    is a swing high (max within +/-3), confirmed and written at bar 3+3=6.
    lows dip independently to 10 at bar 3 too, so a swing low is ALSO
    confirmed by row 6 -- required because detect_liquidity_sweeps() skips
    a bar entirely (both BSL and SSL checks) if EITHER swing_high or
    swing_low is still NaN, so both must be established for the BSL check
    to even run.
    Bar 9 wicks to 115 (>110) but closes at 108 (<=110) -> BSL sweep,
    swept_level_price must equal 110 (the swing high), direction bearish.
    """
    highs = [100, 101, 102, 110, 103, 102, 101, 100, 100, 115, 100, 100]
    lows = [50, 49, 48, 10, 49, 48, 47, 50, 50, 50, 50, 50]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    closes[9] = 108  # bar 9: wick 115 but close back inside (<=110)
    df = _bars(highs, lows, closes)

    out = LiquiditySweepStateEngine().detect_sweeps(df, symbol="TEST", timeframe="h1")

    assert len(out) == 1, f"expected exactly 1 sweep event, got {len(out)}: {out}"
    row = out.iloc[0]
    assert row["sweep_type"] == "bsl"
    assert row["direction"] == "bearish"
    assert row["swept_level_price"] == 110.0
    assert row["bar_datetime"] == df["price_datetime"].iloc[9]
    print("[OK] test_bsl_sweep_detected_and_capped_to_swing_high PASSED")


def test_ssl_sweep_detected():
    """
    Mirror scenario: bar 3 low=10 is a swing low (confirmed at bar 6), highs
    independently peak (harmlessly, not swept) so both swing_high/swing_low
    are non-NaN by row 6. Bar 9 wicks to 5 (<10) but closes at 12 (>=10) ->
    SSL sweep, bullish.
    """
    lows = [50, 49, 48, 10, 49, 48, 47, 50, 50, 5, 50, 50]
    highs = [100, 101, 102, 110, 103, 102, 101, 100, 100, 100, 100, 100]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    closes[9] = 12  # bar 9: wick 5 but close back inside (>=10)
    df = _bars(highs, lows, closes)

    out = LiquiditySweepStateEngine().detect_sweeps(df, symbol="TEST", timeframe="h1")

    assert len(out) == 1, f"expected exactly 1 sweep event, got {len(out)}: {out}"
    row = out.iloc[0]
    assert row["sweep_type"] == "ssl"
    assert row["direction"] == "bullish"
    assert row["swept_level_price"] == 10.0
    print("[OK] test_ssl_sweep_detected PASSED")


def test_wick_through_without_close_back_in_is_not_a_sweep():
    """
    Same swing-high/swing-low setup as test 1, but bar 9 closes at 112
    (still ABOVE the 110 swing high) -> that's a genuine breakout, not a
    sweep. Must NOT be flagged.
    """
    highs = [100, 101, 102, 110, 103, 102, 101, 100, 100, 115, 100, 100]
    lows = [50, 49, 48, 10, 49, 48, 47, 50, 50, 50, 50, 50]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    closes[9] = 112  # close stays ABOVE the swing high -> real breakout, not a sweep
    df = _bars(highs, lows, closes)

    out = LiquiditySweepStateEngine().detect_sweeps(df, symbol="TEST", timeframe="h1")
    assert len(out) == 0, f"expected no sweep events (genuine breakout), got {len(out)}: {out}"
    print("[OK] test_wick_through_without_close_back_in_is_not_a_sweep PASSED")


def test_empty_input_produces_no_rows():
    out = LiquiditySweepStateEngine().detect_sweeps(pd.DataFrame(), symbol="TEST", timeframe="h1")
    assert out.empty
    print("[OK] test_empty_input_produces_no_rows PASSED")


if __name__ == "__main__":
    test_bsl_sweep_detected_and_capped_to_swing_high()
    test_ssl_sweep_detected()
    test_wick_through_without_close_back_in_is_not_a_sweep()
    test_empty_input_produces_no_rows()
    print("\n" + "#" * 60)
    print("   ALL LIQUIDITY SWEEP ENGINE TESTS PASSED")
    print("#" * 60)
