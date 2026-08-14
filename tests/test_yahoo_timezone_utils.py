"""
Unit tests for fetcher/timezone_utils.py's to_utc_naive() -- the fix shared
by yahoo_finance_client.py and market_fetcher.py (and, at the time, the
now-removed sync_step1.py) for the Pass A timezone data-integrity workstream.

Root cause: yfinance returns a tz-aware DatetimeIndex localized to the
source exchange's own timezone (America/New_York for GC=F/DX-Y.NYB/GDX,
Europe/London for EURUSD=X, America/Chicago for ^TNX/^VIX). All three
fetchers previously stripped tzinfo without converting to UTC first
(`.tz_localize(None)` or a bare `.strftime()` on the tz-aware value),
silently writing exchange-local wall-clock time into the DB labeled as UTC.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.timezone_utils import to_utc_naive  # noqa: E402


def test_new_york_summer_offset():
    print("=" * 60)
    print("1. America/New_York (GC=F/DX-Y.NYB/GDX), summer EDT = UTC-4")
    print("=" * 60)
    ts = pd.Timestamp("2026-08-14 08:00:00").tz_localize("America/New_York")
    out = to_utc_naive(ts)
    assert out == pd.Timestamp("2026-08-14 12:00:00")
    assert out.tzinfo is None
    print(f"  [+] 08:00 EDT -> {out} UTC (naive)")
    print("  [OK] test_new_york_summer_offset PASSED\n")


def test_new_york_winter_offset():
    print("=" * 60)
    print("2. America/New_York, winter EST = UTC-5 -- confirms this is")
    print("   derived from tzinfo, not a hardcoded -4h constant")
    print("=" * 60)
    ts = pd.Timestamp("2026-01-14 08:00:00").tz_localize("America/New_York")
    out = to_utc_naive(ts)
    assert out == pd.Timestamp("2026-01-14 13:00:00")
    print(f"  [+] 08:00 EST -> {out} UTC (different offset than summer, correctly DST-aware)")
    print("  [OK] test_new_york_winter_offset PASSED\n")


def test_london_summer_offset():
    print("=" * 60)
    print("3. Europe/London (EURUSD=X), summer BST = UTC+1")
    print("=" * 60)
    ts = pd.Timestamp("2026-08-14 14:00:00").tz_localize("Europe/London")
    out = to_utc_naive(ts)
    assert out == pd.Timestamp("2026-08-14 13:00:00")
    print(f"  [+] 14:00 BST -> {out} UTC")
    print("  [OK] test_london_summer_offset PASSED\n")


def test_chicago_offset():
    print("=" * 60)
    print("4. America/Chicago (^TNX/^VIX), summer CDT = UTC-5")
    print("=" * 60)
    ts = pd.Timestamp("2026-08-14 09:00:00").tz_localize("America/Chicago")
    out = to_utc_naive(ts)
    assert out == pd.Timestamp("2026-08-14 14:00:00")
    print(f"  [+] 09:00 CDT -> {out} UTC")
    print("  [OK] test_chicago_offset PASSED\n")


def test_already_naive_timestamp_passes_through_unchanged():
    print("=" * 60)
    print("5. A naive (no tzinfo) timestamp is returned unchanged, not")
    print("   guessed at -- avoids silently mislabeling an edge case")
    print("=" * 60)
    ts = pd.Timestamp("2026-08-14 09:00:00")
    out = to_utc_naive(ts)
    assert out == ts
    print("  [+] naive input passed through as-is")
    print("  [OK] test_already_naive_timestamp_passes_through_unchanged PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   fetcher.timezone_utils.to_utc_naive — TESTS")
    print("#" * 60 + "\n")

    test_new_york_summer_offset()
    test_new_york_winter_offset()
    test_london_summer_offset()
    test_chicago_offset()
    test_already_naive_timestamp_passes_through_unchanged()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
