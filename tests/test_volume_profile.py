"""
Unit tests for analysis.volume_profile (Phase 2d).

Unlike the other Phase tests, VolumeProfileCalculator (binning, POC, Value
Area, HVN/LVN) is pre-existing code, only its HVN/LVN local-extrema logic
was fixed here — that fix, and the new SessionVolumeProfileEngine
(per-UTC-day session grouping + persistence-shaped bin rows), are what
these tests actually exercise, using a hand-constructed volume
distribution where POC/VAH/VAL/HVN/LVN can all be verified by hand.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.volume_profile.calculator import VolumeProfileCalculator  # noqa: E402
from analysis.volume_profile.session_profile import SessionVolumeProfileEngine, MIN_BARS_PER_SESSION  # noqa: E402


def test_poc_and_value_area_hand_calculated():
    print("=" * 60)
    print("1. POC + Value Area (70%) on a hand-calculable distribution")
    print("=" * 60)

    # 10 points spaced 1.0 apart, data min/max = 100.5/109.5 -> bin width =
    # (109.5-100.5)/10 = 0.9 (bins are built from the data's own min/max,
    # not an assumed round range) -> bin edges 100.5, 101.4, 102.3, ...,
    # 109.5, bin centers 100.95, 101.85, ..., 109.05. Points are spaced
    # 1.0 apart (> the 0.9 bin width) so each falls in its own bin, giving
    # bin_volumes == the volumes list below, in order.
    closes  = [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5, 108.5, 109.5]
    volumes = [   5,     5,    10,    50,   100,    60,    20,     5,     5,     5]
    # total = 265, target 70% = 185.5
    # POC = bin idx 4 (center 104.55, vol=100)
    # expand: left(idx3,vol50) vs right(idx5,vol60) -> right wins: acc=100+60=160
    #         left(idx3,vol50) vs right(idx6,vol20) -> left wins: acc=160+50=210 >= 185.5 stop
    # VA = bins [3..5] = centers 103.65 to 105.45 -> val=103.65, vah=105.45
    df = pd.DataFrame({"close_price": closes, "volume": volumes})

    calc = VolumeProfileCalculator(num_bins=10, value_area_pct=0.70)
    profile = calc.compute_profile(df)

    assert profile["poc"] == 104.55, profile["poc"]
    assert profile["val"] == 103.65, profile["val"]
    assert profile["vah"] == 105.45, profile["vah"]
    assert profile["total_volume"] == 265.0

    print(f"  [+] poc={profile['poc']} val={profile['val']} vah={profile['vah']} total={profile['total_volume']}")
    print("  [OK] test_poc_and_value_area_hand_calculated PASSED\n")


def test_hvn_lvn_local_extrema():
    print("=" * 60)
    print("2. HVN/LVN: local extrema relative to immediate neighbors only")
    print("=" * 60)

    # bin volumes by construction (1 bar per bin center, num_bins=8):
    # idx:    0   1   2   3   4   5   6   7
    # vol:   10  30  10  10  80  10  40  10
    # local maxima (strictly > both neighbors): idx1(30>10,30>10), idx4(80>10,80>10), idx6(40>10,40>10)
    # local minima (strictly < both neighbors): idx2(10<30,10<10? NO -- 10==10 not strict) -> check carefully below
    closes  = [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5]
    volumes = [   10,    30,    10,    10,    80,    10,    40,    10]
    df = pd.DataFrame({"close_price": closes, "volume": volumes})

    calc = VolumeProfileCalculator(num_bins=8, value_area_pct=0.70)
    profile = calc.compute_profile(df)

    # idx0 and idx7 excluded (no two neighbors)
    # idx1: 30 > vol[0]=10 and 30 > vol[2]=10 -> HVN
    # idx2: 10 < vol[1]=30 but 10 == vol[3]=10 -> NOT strictly less -> not LVN
    # idx3: 10 == vol[2]=10 -> not strictly less than left -> not LVN
    # idx4: 80 > vol[3]=10 and 80 > vol[5]=10 -> HVN
    # idx5: 10 < vol[4]=80 and 10 < vol[6]=40 -> LVN
    # idx6: 40 > vol[5]=10 and 40 > vol[7]=10 -> HVN
    assert set(profile["hvn_indices"]) == {1, 4, 6}, profile["hvn_indices"]
    assert set(profile["lvn_indices"]) == {5}, profile["lvn_indices"]
    assert 0 not in profile["hvn_indices"] and 7 not in profile["hvn_indices"], "edge bins must be excluded"

    print(f"  [+] hvn_indices={profile['hvn_indices']}  lvn_indices={profile['lvn_indices']}")
    print("  [OK] test_hvn_lvn_local_extrema PASSED\n")


def test_session_profile_groups_by_utc_day():
    print("=" * 60)
    print("3. SessionVolumeProfileEngine: per-UTC-day grouping + bin rows")
    print("=" * 60)

    # Day 1: 6 bars (>= MIN_BARS_PER_SESSION) -> should produce a profile
    # Day 2: 2 bars (< MIN_BARS_PER_SESSION) -> should be skipped
    day1 = pd.date_range("2026-01-01 00:00", periods=6, freq="h")
    day2 = pd.date_range("2026-01-02 00:00", periods=2, freq="h")
    dt = list(day1) + list(day2)
    closes = [100, 101, 102, 103, 104, 105, 200, 201]
    volumes = [10, 20, 30, 100, 50, 20, 5, 5]

    df = pd.DataFrame({"price_datetime": dt, "close_price": closes, "volume": volumes})
    assert MIN_BARS_PER_SESSION == 4

    engine = SessionVolumeProfileEngine(num_bins=5, value_area_pct=0.70)
    rows = engine.compute_session_profiles(df, symbol="TEST", timeframe="h1")

    sessions = rows["session_date"].unique()
    assert len(sessions) == 1, f"day 2 (only 2 bars) must be skipped, got sessions: {sessions}"
    assert str(sessions[0]) == "2026-01-01"

    assert len(rows) == 5, f"expected 5 bin rows (num_bins=5) for the one valid session, got {len(rows)}"
    assert (rows["symbol"] == "TEST").all()
    assert (rows["timeframe"] == "h1").all()
    assert (rows["num_bins"] == 5).all()

    poc_rows = rows[rows["is_poc"]]
    assert len(poc_rows) == 1, "exactly one bin must be flagged as POC"
    assert poc_rows.iloc[0]["session_poc"] == poc_rows.iloc[0]["bin_center"]

    va_rows = rows[rows["in_value_area"]]
    assert len(va_rows) >= 1
    assert (va_rows["bin_center"] >= va_rows["session_val"].iloc[0]).all()
    assert (va_rows["bin_center"] <= va_rows["session_vah"].iloc[0]).all()

    print(f"  [+] sessions found: {list(sessions)}  bin rows: {len(rows)}")
    print(f"  [+] POC bin: center={poc_rows.iloc[0]['bin_center']}  in {len(va_rows)} value-area bins")
    print("  [OK] test_session_profile_groups_by_utc_day PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   VOLUME PROFILE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_poc_and_value_area_hand_calculated()
    test_hvn_lvn_local_extrema()
    test_session_profile_groups_by_utc_day()

    print("#" * 60)
    print("   ALL VOLUME PROFILE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
