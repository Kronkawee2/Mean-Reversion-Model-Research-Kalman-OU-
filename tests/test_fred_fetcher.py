"""
Unit tests for fetcher/fred_fetcher.py's parse_fred_dataframe() -- the
column-mapping/type-coercion logic split out from fetch_series() so it can
run against a small in-memory DataFrame instead of a real network call.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.fred_fetcher import parse_fred_dataframe  # noqa: E402


def _source_frame(series_id, values, dates=None):
    """Shape matches the real FRED CSV: observation_date,<SERIES_ID>."""
    dates = dates or ["2026-08-11", "2026-08-12", "2026-08-13"]
    return pd.DataFrame({"observation_date": dates, series_id: values})


def test_maps_series_column_to_requested_value_col_name():
    print("=" * 60)
    print("1. observation_date -> report_date, <SERIES_ID> -> caller's value_col")
    print("=" * 60)
    df = _source_frame("DFF", [3.63, 3.63, 3.63])
    records = parse_fred_dataframe(df, "DFF", "rate_pct")
    assert len(records) == 3
    assert set(records[0].keys()) == {"report_date", "rate_pct"}
    print(f"  parsed columns: {sorted(records[0].keys())}")
    print("PASS\n")


def test_values_match_real_sample_exactly():
    print("=" * 60)
    print("2. Parsed values match the real 2026-08-13/2026-07-01 samples from the feasibility survey")
    print("=" * 60)
    dff = parse_fred_dataframe(_source_frame("DFF", [3.63, 3.63, 3.63]), "DFF", "rate_pct")
    tips = parse_fred_dataframe(_source_frame("DFII10", [2.40, 2.43, 2.39]), "DFII10", "real_yield_pct")
    cpi = parse_fred_dataframe(
        _source_frame("CPIAUCSL", [330.293, 332.407, 332.813], dates=["2026-03-01", "2026-04-01", "2026-07-01"]),
        "CPIAUCSL", "cpi_index",
    )
    assert dff[-1] == {"report_date": pd.Timestamp("2026-08-13").date(), "rate_pct": 3.63}
    assert tips[-1] == {"report_date": pd.Timestamp("2026-08-13").date(), "real_yield_pct": 2.39}
    assert cpi[-1] == {"report_date": pd.Timestamp("2026-07-01").date(), "cpi_index": 332.813}
    print(f"  DFF: {dff[-1]}")
    print(f"  DFII10: {tips[-1]}")
    print(f"  CPIAUCSL: {cpi[-1]}")
    print("PASS\n")


def test_missing_value_marker_dropped_not_fatal():
    print("=" * 60)
    print("3. FRED's '.' missing-observation marker is dropped, not fatal")
    print("=" * 60)
    df = _source_frame("DFII10", ["2.40", ".", "2.39"])
    records = parse_fred_dataframe(df, "DFII10", "real_yield_pct")
    assert len(records) == 2
    print(f"  {len(records)} of 3 rows kept")
    print("PASS\n")


def test_unparseable_date_dropped_not_fatal():
    print("=" * 60)
    print("4. Rows with an unparseable date are dropped, not fatal")
    print("=" * 60)
    df = _source_frame("DFF", [3.63, 3.63, 3.63], dates=["2026-08-11", "not-a-date", "2026-08-13"])
    records = parse_fred_dataframe(df, "DFF", "rate_pct")
    assert len(records) == 2
    print(f"  {len(records)} of 3 rows kept")
    print("PASS\n")


def test_duplicate_dates_deduplicated():
    print("=" * 60)
    print("5. Duplicate report_date rows are deduplicated")
    print("=" * 60)
    df = _source_frame("DFF", [3.63, 3.63, 3.63], dates=["2026-08-11", "2026-08-11", "2026-08-13"])
    records = parse_fred_dataframe(df, "DFF", "rate_pct")
    dates = [r["report_date"] for r in records]
    assert len(dates) == len(set(dates))
    print(f"  {len(records)} unique dates from 3 input rows")
    print("PASS\n")


if __name__ == "__main__":
    test_maps_series_column_to_requested_value_col_name()
    test_values_match_real_sample_exactly()
    test_missing_value_marker_dropped_not_fatal()
    test_unparseable_date_dropped_not_fatal()
    test_duplicate_dates_deduplicated()
    print("All FRED fetcher tests passed.")
