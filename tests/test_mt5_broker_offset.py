"""
Unit tests for the broker-vs-true-UTC offset calibration/correction added
to mt5_data_fetcher.py (Pass A of the timezone data-integrity workstream).

Root cause: the broker's raw epoch timestamps (both ticks and rates) run
ahead of true UTC by a DST-dependent amount (measured +3h/EEST at the time
this was found), confirmed via a live cross-check against the system's own
UTC clock. Since this shifts with DST, it's measured fresh via
check_symbol() -> _calibrate_broker_utc_offset() rather than hardcoded, and
subtracted from every rates/ticks dataframe before it's returned.

These tests don't need a live MT5 connection -- they exercise the pure
calibration/correction logic directly, with a stubbed tick object and
synthetic dataframes.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sync.mt5_data_fetcher import MT5DataFetcher  # noqa: E402


class _StubTick:
    def __init__(self, time):
        self.time = time


def test_calibration_measures_offset_against_true_utc():
    print("=" * 60)
    print("1. _calibrate_broker_utc_offset measures broker-clock-minus-")
    print("   true-UTC and stores it (not a hardcoded constant)")
    print("=" * 60)

    import scripts.sync.mt5_data_fetcher as mod

    true_now = pd.Timestamp.now(tz="UTC")
    broker_epoch = int((true_now + pd.Timedelta(hours=3)).timestamp())  # simulate EEST, +3h ahead

    class _StubMT5:
        @staticmethod
        def symbol_info_tick(symbol):
            return _StubTick(broker_epoch)

        @staticmethod
        def last_error():
            return (0, "no error")

    original_mt5 = mod.mt5
    mod.mt5 = _StubMT5
    try:
        fetcher = MT5DataFetcher()
        assert fetcher.broker_utc_offset is None
        fetcher._calibrate_broker_utc_offset("XAUUSD")
        offset_hours = fetcher.broker_utc_offset.total_seconds() / 3600
        assert 2.99 < offset_hours < 3.01, f"expected ~+3h offset, got {offset_hours}h"
    finally:
        mod.mt5 = original_mt5

    print(f"  [+] measured offset: {fetcher.broker_utc_offset} (~+3h, matches simulated EEST broker clock)")
    print("  [OK] test_calibration_measures_offset_against_true_utc PASSED\n")


def test_correct_to_true_utc_subtracts_the_calibrated_offset():
    print("=" * 60)
    print("2. _correct_to_true_utc subtracts the calibrated offset from")
    print("   time_utc/time so returned bars are true UTC, not broker time")
    print("=" * 60)

    fetcher = MT5DataFetcher()
    fetcher.broker_utc_offset = pd.Timedelta(hours=3)

    broker_labeled = pd.Timestamp("2026-08-14T15:00:00Z")
    df = pd.DataFrame({
        "time_utc": [broker_labeled],
        "time": [broker_labeled.tz_localize(None)],
        "open": [4000.0], "high": [4001.0], "low": [3999.0], "close": [4000.5],
        "tick_volume": [10], "spread": [1], "real_volume": [0],
    })

    out = fetcher._correct_to_true_utc(df)

    assert out["time_utc"].iloc[0] == pd.Timestamp("2026-08-14T12:00:00Z")
    print(f"  [+] broker-labeled 15:00 -3h offset -> true UTC {out['time_utc'].iloc[0]}")
    print("  [OK] test_correct_to_true_utc_subtracts_the_calibrated_offset PASSED\n")


def test_uncalibrated_fetcher_raises_rather_than_silently_using_zero_offset():
    print("=" * 60)
    print("3. Calling rates/ticks correction before calibration raises --")
    print("   never silently falls back to an uncorrected (zero) offset")
    print("=" * 60)

    fetcher = MT5DataFetcher()
    df = pd.DataFrame({
        "time_utc": [pd.Timestamp("2026-08-14T15:00:00Z")],
        "time": [pd.Timestamp("2026-08-14 15:00:00")],
        "open": [4000.0], "high": [4001.0], "low": [3999.0], "close": [4000.5],
        "tick_volume": [10], "spread": [1], "real_volume": [0],
    })

    raised = False
    try:
        fetcher._correct_to_true_utc(df)
    except Exception as e:
        raised = True
        assert "not calibrated" in str(e)

    assert raised, "expected _correct_to_true_utc to raise when broker_utc_offset is None"
    print("  [+] raised MT5DataError instead of silently returning uncorrected data")
    print("  [OK] test_uncalibrated_fetcher_raises_rather_than_silently_using_zero_offset PASSED\n")


def test_empty_dataframe_skips_correction_without_requiring_calibration():
    print("=" * 60)
    print("4. An empty dataframe passes through without requiring")
    print("   calibration (nothing to correct)")
    print("=" * 60)

    fetcher = MT5DataFetcher()
    empty = pd.DataFrame(columns=["time_utc", "time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
    out = fetcher._correct_to_true_utc(empty)
    assert out.empty

    print("  [+] empty df returned as-is, no calibration error raised")
    print("  [OK] test_empty_dataframe_skips_correction_without_requiring_calibration PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   MT5DataFetcher — BROKER UTC OFFSET CALIBRATION/CORRECTION TESTS")
    print("#" * 60 + "\n")

    test_calibration_measures_offset_against_true_utc()
    test_correct_to_true_utc_subtracts_the_calibrated_offset()
    test_uncalibrated_fetcher_raises_rather_than_silently_using_zero_offset()
    test_empty_dataframe_skips_correction_without_requiring_calibration()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
