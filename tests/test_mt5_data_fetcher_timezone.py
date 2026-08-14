"""
Unit test for the _to_naive_utc() local-timezone fix in mt5_data_fetcher.py.

Root cause: mt5.copy_rates_range() silently reinterprets a naive
datetime.datetime using the LOCAL SYSTEM TIMEZONE, not UTC -- a documented
quirk of the MetaTrader5 Python API. The old _to_naive_utc() converted to
UTC wall-clock numbers and stripped tzinfo, which then got re-interpreted
by MT5 as local time, silently shifting every range query by the local
UTC offset. Confirmed empirically on the machine this was found on
(UTC+7): passing labeled-UTC bounds [X, Y] to get_rates() returned bars
labeled [X-7h, Y-7h] instead, verified against get_latest_rates() (a
position-based call, unaffected, cross-checked against symbol_info_tick's
raw epoch as ground truth).

Fix: convert to LOCAL wall-clock time before stripping tzinfo, so that
MT5's own local->UTC reinterpretation lands back on the UTC instant
actually intended. This test doesn't need a live MT5 connection -- it
only checks _to_naive_utc()'s pure conversion math against the system's
own UTC offset.
"""

import datetime
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sync.mt5_data_fetcher import _to_naive_utc  # noqa: E402


def test_to_naive_utc_adds_local_offset():
    print("=" * 60)
    print("1. _to_naive_utc converts to LOCAL wall-clock time, not UTC")
    print("   wall-clock time -- this is what MT5's API actually expects")
    print("=" * 60)

    ts = pd.Timestamp("2026-08-14T14:40:00Z")
    out = _to_naive_utc(ts)

    local_offset = datetime.datetime.now().astimezone().utcoffset()
    expected = ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None) + local_offset

    assert out == expected, f"expected {expected}, got {out}"
    assert out.tzinfo is None, "must return a naive datetime (what mt5.copy_rates_range expects)"

    print(f"  [+] input UTC 14:40:00 + local offset {local_offset} -> {out} (naive, local wall-clock)")
    print("  [OK] test_to_naive_utc_adds_local_offset PASSED\n")


def test_to_naive_utc_roundtrips_through_local_offset_symmetrically():
    print("=" * 60)
    print("2. Two timestamps N hours apart in UTC stay N hours apart after")
    print("   conversion -- the fix only shifts, never distorts, durations")
    print("=" * 60)

    ts1 = pd.Timestamp("2026-08-14T10:00:00Z")
    ts2 = pd.Timestamp("2026-08-14T13:30:00Z")

    out1 = _to_naive_utc(ts1)
    out2 = _to_naive_utc(ts2)

    assert (out2 - out1) == datetime.timedelta(hours=3, minutes=30)

    print(f"  [+] gap preserved: {out2 - out1}")
    print("  [OK] test_to_naive_utc_roundtrips_through_local_offset_symmetrically PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   MT5DataFetcher._to_naive_utc — LOCAL TIMEZONE FIX TESTS")
    print("#" * 60 + "\n")

    test_to_naive_utc_adds_local_offset()
    test_to_naive_utc_roundtrips_through_local_offset_symmetrically()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
