"""
Unit tests for fetcher/ecb_fetcher.py's parse_ecb_dataframe() -- the
column-mapping/type-coercion logic split out from fetch_series() so it can
run against a small in-memory DataFrame instead of a real network call.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.ecb_fetcher import parse_ecb_dataframe  # noqa: E402


def _source_frame(dates=None, values=None):
    """Shape matches the real ECB SDMX csvdata response: TIME_PERIOD/
    OBS_VALUE plus ~30 metadata columns this project doesn't persist."""
    dates = dates or ["2026-08-11", "2026-08-12", "2026-08-13"]
    values = values or [3.1760932477, 3.1654173208, 3.155665028]
    return pd.DataFrame({
        "KEY": ["YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"] * len(dates),
        "FREQ": ["B"] * len(dates),
        "TIME_PERIOD": dates,
        "OBS_VALUE": values,
        "OBS_STATUS": ["A"] * len(dates),
        "TITLE_COMPL": ["Euro area ... 10-year maturity"] * len(dates),
    })


def test_maps_ecb_columns_and_drops_metadata():
    print("=" * 60)
    print("1. TIME_PERIOD/OBS_VALUE mapped, ~30 metadata columns dropped")
    print("=" * 60)
    records = parse_ecb_dataframe(_source_frame())
    assert len(records) == 3
    assert set(records[0].keys()) == {"report_date", "yield_pct"}
    print(f"  parsed columns: {sorted(records[0].keys())}")
    print("PASS\n")


def test_values_match_real_sample_exactly():
    print("=" * 60)
    print("2. Parsed values match the real 2026-08-13 sample from the feasibility survey")
    print("=" * 60)
    records = parse_ecb_dataframe(_source_frame())
    last = records[-1]
    assert last["report_date"] == pd.Timestamp("2026-08-13").date()
    assert abs(last["yield_pct"] - 3.155665028) < 1e-9
    print(f"  {last}")
    print("PASS\n")


def test_unparseable_date_dropped_not_fatal():
    print("=" * 60)
    print("3. Rows with an unparseable date are dropped, not fatal")
    print("=" * 60)
    df = _source_frame(dates=["2026-08-11", "not-a-date", "2026-08-13"])
    records = parse_ecb_dataframe(df)
    assert len(records) == 2
    print(f"  {len(records)} of 3 rows kept")
    print("PASS\n")


def test_non_numeric_value_dropped_not_fatal():
    print("=" * 60)
    print("4. A non-numeric OBS_VALUE is dropped, not fatal")
    print("=" * 60)
    df = _source_frame(values=[3.176, "N/A", 3.156])
    records = parse_ecb_dataframe(df)
    assert len(records) == 2
    print(f"  {len(records)} of 3 rows kept")
    print("PASS\n")


def test_duplicate_dates_deduplicated():
    print("=" * 60)
    print("5. Duplicate report_date rows are deduplicated")
    print("=" * 60)
    df = _source_frame(dates=["2026-08-11", "2026-08-11", "2026-08-13"])
    records = parse_ecb_dataframe(df)
    dates = [r["report_date"] for r in records]
    assert len(dates) == len(set(dates))
    print(f"  {len(records)} unique dates from 3 input rows")
    print("PASS\n")


if __name__ == "__main__":
    test_maps_ecb_columns_and_drops_metadata()
    test_values_match_real_sample_exactly()
    test_unparseable_date_dropped_not_fatal()
    test_non_numeric_value_dropped_not_fatal()
    test_duplicate_dates_deduplicated()
    print("All ECB fetcher tests passed.")
