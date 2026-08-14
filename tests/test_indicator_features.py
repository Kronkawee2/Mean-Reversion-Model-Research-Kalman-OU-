"""
Unit tests for analysis.features.indicator_features (Phase 2c EMA/ATR/RSI,
Phase 2f OBV, Phase 2g Stochastic %K/%D + CCI 20).

calc_ema/calc_rsi/calc_atr/calc_obv themselves are pre-existing,
already-used code (analysis.technical_analysis) — not re-tested for their
own formulas here. calc_stochastic/calc_cci, by contrast, are new code
written directly in this module (no existing implementation was found
anywhere in the codebase — see indicator_features.py's module docstring),
so their formulas ARE exercised here bar-by-bar against hand-verified
values, the same standard OBV got in Phase 2f. These tests check:
(1) calc_indicator_features wires EMA/RSI/ATR together and outputs the
right shape/columns against a hand-calculable close sequence,
(2) resample_ohlc produces correct 1h->6h OHLC aggregation and aligns
buckets to 00/06/12/18 UTC, (3) OBV's exact running cumulative value at
each bar of a hand-calculable up/down/flat close+volume sequence, and
(4)/(5) Stochastic %K/%D and CCI 20 against hand-verified values on a
constant-slope OHLC ramp (chosen because a linear ramp keeps both
indicators at a single, hand-checkable constant value once past warm-up,
which isn't true of an arbitrary sequence).
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.features.indicator_features import (  # noqa: E402
    calc_indicator_features, resample_ohlc, calc_stochastic, calc_cci,
    EMA_PERIODS, ATR_PERIOD, RSI_PERIOD, STOCH_PERIOD, STOCH_SMOOTH_K, STOCH_SMOOTH_D, CCI_PERIOD,
)
from analysis.technical_analysis.trend import calc_ema  # noqa: E402
from analysis.technical_analysis.momentum import calc_rsi  # noqa: E402
from analysis.technical_analysis.volatility import calc_atr  # noqa: E402
from analysis.technical_analysis.volume import calc_obv  # noqa: E402


def _ohlc_df(start, rows):
    n = len(rows)
    dt = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({
        "price_datetime": dt,
        "open_price":  [r[0] for r in rows],
        "high_price":  [r[1] for r in rows],
        "low_price":   [r[2] for r in rows],
        "close_price": [r[3] for r in rows],
    })


def test_calc_indicator_features_matches_underlying_functions():
    print("=" * 60)
    print("1. calc_indicator_features reuses calc_ema/calc_rsi/calc_atr exactly")
    print("=" * 60)

    np.random.seed(42)
    n = 60
    closes = 100 + np.cumsum(np.random.randn(n) * 0.5)
    rows = []
    for c in closes:
        o = c - 0.1
        h = c + abs(np.random.randn()) * 0.3
        l = c - abs(np.random.randn()) * 0.3
        rows.append((o, h, l, c))
    df = _ohlc_df("2026-01-01", rows)

    out = calc_indicator_features(df, symbol="XAUUSD", timeframe="h1")

    assert list(out.columns) == ["symbol", "timeframe", "bar_datetime",
                                  "ema_20", "ema_50", "ema_200", "atr_14", "rsi_14", "obv",
                                  "stoch_k", "stoch_d", "cci_20"]
    assert len(out) == n
    assert (out["symbol"] == "XAUUSD").all()
    assert (out["timeframe"] == "h1").all()

    expected_ema20 = calc_ema(df["close_price"], 20)
    expected_atr14 = calc_atr(df, 14)
    expected_rsi14 = calc_rsi(df["close_price"], 14)

    pd.testing.assert_series_equal(out["ema_20"], expected_ema20, check_names=False)
    pd.testing.assert_series_equal(out["atr_14"], expected_atr14, check_names=False)
    pd.testing.assert_series_equal(out["rsi_14"], expected_rsi14, check_names=False)

    assert EMA_PERIODS == (20, 50, 200)
    assert ATR_PERIOD == 14
    assert RSI_PERIOD == 14

    print(f"  [+] {len(out)} rows, columns match, values identical to calc_ema/calc_rsi/calc_atr")
    print("  [OK] test_calc_indicator_features_matches_underlying_functions PASSED\n")


def test_resample_ohlc_1h_to_6h():
    print("=" * 60)
    print("2. resample_ohlc: 1h -> 6h OHLC aggregation, aligned to 00/06/12/18 UTC")
    print("=" * 60)

    # Two full 6h buckets: 00:00-05:00 and 06:00-11:00 on 2026-01-01 UTC
    rows = [
        # bucket 1 (00:00-05:00): open=100 (bar0), high=110 (bar2), low=95 (bar4), close=104 (bar5)
        (100, 102, 99, 101),   # 00:00
        (101, 105, 100, 103),  # 01:00
        (103, 110, 102, 108),  # 02:00
        (108, 109, 104, 105),  # 03:00
        (105, 106, 95, 97),    # 04:00
        (97, 104, 96, 104),    # 05:00
        # bucket 2 (06:00-11:00): open=104 (bar6), high=120, low=100, close=115
        (104, 106, 100, 105),  # 06:00
        (105, 120, 103, 118),  # 07:00
        (118, 119, 110, 115),  # 08:00
    ]
    df = _ohlc_df("2026-01-01 00:00", rows)
    out = resample_ohlc(df, rule="6h")

    assert len(out) == 2, f"expected 2 buckets, got {len(out)}\n{out}"

    b1 = out.iloc[0]
    assert b1["price_datetime"] == pd.Timestamp("2026-01-01 00:00")
    assert b1["open_price"] == 100
    assert b1["high_price"] == 110
    assert b1["low_price"] == 95
    assert b1["close_price"] == 104

    b2 = out.iloc[1]
    assert b2["price_datetime"] == pd.Timestamp("2026-01-01 06:00")
    assert b2["open_price"] == 104
    assert b2["high_price"] == 120
    assert b2["low_price"] == 100
    assert b2["close_price"] == 115

    print(f"  [+] bucket1 00:00 O={b1['open_price']} H={b1['high_price']} L={b1['low_price']} C={b1['close_price']}")
    print(f"  [+] bucket2 06:00 O={b2['open_price']} H={b2['high_price']} L={b2['low_price']} C={b2['close_price']}")
    print("  [OK] test_resample_ohlc_1h_to_6h PASSED\n")


def test_obv_hand_calculable_sequence():
    print("=" * 60)
    print("3. OBV: exact running cumulative value on a hand-calculable up/down/flat sequence")
    print("=" * 60)

    # bar0: no prior close -> OBV=0
    # bar1: close 102>100 (up)   -> OBV = 0 + 20 = 20
    # bar2: close 101<102 (down) -> OBV = 20 - 15 = 5
    # bar3: close 101==101 (flat)-> OBV unchanged = 5
    # bar4: close 103>101 (up)   -> OBV = 5 + 30 = 35
    # bar5: close 100<103 (down) -> OBV = 35 - 25 = 10
    closes  = [100, 102, 101, 101, 103, 100]
    volumes = [ 10,  20,  15,   5,  30,  25]
    expected_obv = [0, 20, 5, 5, 35, 10]

    rows = [(c, c, c, c) for c in closes]  # OHLC not used by OBV, only close+volume
    df = _ohlc_df("2026-01-01", rows)
    df["volume"] = volumes

    out = calc_indicator_features(df, symbol="XAUUSD", timeframe="h1")
    assert out["obv"].tolist() == expected_obv, out["obv"].tolist()

    # Also matches calc_obv called directly (calc_indicator_features must
    # not be reimplementing OBV, just wiring the existing function).
    pd.testing.assert_series_equal(out["obv"].reset_index(drop=True), calc_obv(df).rename("obv"), check_names=False)

    print(f"  [+] OBV running values: {out['obv'].tolist()}")
    print("  [OK] test_obv_hand_calculable_sequence PASSED\n")


def test_stochastic_hand_verified_on_linear_ramp():
    print("=" * 60)
    print("4. Stochastic %K/%D: hand-verified on a constant-slope OHLC ramp")
    print("=" * 60)

    # high_i=110+i, low_i=100+i, close_i=105+i -> constant range (10) and
    # constant relative close position each bar, so raw %K (and its
    # smoothed %K/%D) settle to one constant value past warm-up, which can
    # be hand-verified exactly:
    #   window i=0..13 (period=14): low_n=100, high_n=123, close_13=118
    #   raw %K = 100*(118-100)/(123-100) = 100*18/23 = 78.260869...
    # Since raw %K is identical on every subsequent bar (same constant
    # ramp), smoothing (SMA of smooth_k=3, then smooth_d=3) of a constant
    # series returns that same constant, so %K and %D both settle at
    # 78.261 (rounded to 3dp) from bar 17 onward (14 warm-up + smooth_k-1 + smooth_d-1 = 17).
    assert (STOCH_PERIOD, STOCH_SMOOTH_K, STOCH_SMOOTH_D) == (14, 3, 3)

    n = 25
    df = pd.DataFrame({
        "high_price": [110.0 + i for i in range(n)],
        "low_price":  [100.0 + i for i in range(n)],
        "close_price": [105.0 + i for i in range(n)],
    })
    stoch = calc_stochastic(df)

    assert stoch["stoch_k"].iloc[:15].isna().all(), "no %K before the 14-period window is filled"
    assert stoch["stoch_d"].iloc[:17].isna().all(), "no %D before %K itself has 3 values to smooth"
    assert stoch["stoch_k"].iloc[17] == 78.261, stoch["stoch_k"].iloc[17]
    assert stoch["stoch_d"].iloc[17] == 78.261, stoch["stoch_d"].iloc[17]
    assert stoch["stoch_k"].iloc[-1] == 78.261 and stoch["stoch_d"].iloc[-1] == 78.261

    print(f"  [+] %K={stoch['stoch_k'].iloc[17]}  %D={stoch['stoch_d'].iloc[17]} (hand-calc: 100*18/23=78.2609)")
    print("  [OK] test_stochastic_hand_verified_on_linear_ramp PASSED\n")


def test_cci_hand_verified_on_linear_ramp():
    print("=" * 60)
    print("5. CCI 20: hand-verified on the same constant-slope OHLC ramp")
    print("=" * 60)

    # TP_i = (high_i+low_i+close_i)/3 = 105+i (a pure +1/bar ramp).
    # Window i=0..19 (period=20): TP values 105..124, mean=114.5.
    # TP_19 - mean = 124 - 114.5 = 9.5.
    # Mean absolute deviation of 105..124 around 114.5: distances are
    # 0.5,1.5,...,9.5 (each appearing twice) -> mean = (0.5+9.5)/2 = 5.0.
    # CCI = 9.5 / (0.015 * 5.0) = 9.5 / 0.075 = 126.6667.
    assert CCI_PERIOD == 20

    n = 25
    df = pd.DataFrame({
        "high_price": [110.0 + i for i in range(n)],
        "low_price":  [100.0 + i for i in range(n)],
        "close_price": [105.0 + i for i in range(n)],
    })
    cci = calc_cci(df)

    assert cci.iloc[:19].isna().all(), "no CCI before the 20-period window is filled"
    assert cci.iloc[19] == 126.667, cci.iloc[19]
    assert cci.iloc[-1] == 126.667

    print(f"  [+] CCI={cci.iloc[19]} (hand-calc: 9.5/(0.015*5.0)=126.6667)")
    print("  [OK] test_cci_hand_verified_on_linear_ramp PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   INDICATOR FEATURES — UNIT TESTS")
    print("#" * 60 + "\n")

    test_calc_indicator_features_matches_underlying_functions()
    test_resample_ohlc_1h_to_6h()
    test_obv_hand_calculable_sequence()
    test_stochastic_hand_verified_on_linear_ramp()
    test_cci_hand_verified_on_linear_ramp()

    print("#" * 60)
    print("   ALL INDICATOR-FEATURE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
