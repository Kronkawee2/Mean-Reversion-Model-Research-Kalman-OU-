"""
Unit tests for fetcher/gpr_fetcher.py's parse_gpr_dataframe() -- the
column-mapping/type-coercion logic split out from fetch_history() so it
can run against a small in-memory DataFrame instead of a real network call
or a fabricated .xls binary.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fetcher.gpr_fetcher import parse_gpr_dataframe  # noqa: E402


def _source_frame(**overrides) -> pd.DataFrame:
    """Shape matches the real file: uppercase columns, extra columns this
    project doesn't persist, a 'date' column (not 'report_date')."""
    base = {
        "DAY": [20260808, 20260809, 20260810],
        "N10D": [457, 371, 342],
        "GPRD": [101.48, 71.43, 154.97],
        "GPRD_ACT": [130.07, 89.01, 173.81],
        "GPRD_THREAT": [84.38, 44.55, 209.41],
        "date": ["2026-08-08", "2026-08-09", "2026-08-10"],
        "GPRD_MA30": [184.72, 181.94, 181.56],
        "GPRD_MA7": [142.39, 139.59, 132.01],
        "event": [np.nan, np.nan, np.nan],
        "var_name": [np.nan, np.nan, np.nan],
        "var_label": [np.nan, np.nan, np.nan],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_maps_uppercase_columns_and_date_to_report_date():
    print("=" * 60)
    print("1. Uppercase source columns lowercased, 'date' -> 'report_date'")
    print("=" * 60)
    records = parse_gpr_dataframe(_source_frame())
    assert len(records) == 3
    assert set(records[0].keys()) == {
        "report_date", "gprd", "gprd_act", "gprd_threat", "gprd_ma7", "gprd_ma30",
    }
    print(f"  parsed columns: {sorted(records[0].keys())}")
    print("PASS\n")


def test_values_match_real_sample_exactly():
    print("=" * 60)
    print("2. Parsed values match the real 2026-08-10 sample from the feasibility survey")
    print("=" * 60)
    records = parse_gpr_dataframe(_source_frame())
    last = records[-1]
    assert last["report_date"] == pd.Timestamp("2026-08-10").date()
    assert last["gprd"] == 154.97
    assert last["gprd_act"] == 173.81
    assert last["gprd_threat"] == 209.41
    assert last["gprd_ma7"] == 132.01
    assert last["gprd_ma30"] == 181.56
    print(f"  {last}")
    print("PASS\n")


def test_unparseable_rows_dropped_not_crashed_on():
    print("=" * 60)
    print("3. Rows with an unparseable date are dropped, not fatal")
    print("=" * 60)
    df = _source_frame(date=["2026-08-08", "not-a-date", "2026-08-10"])
    records = parse_gpr_dataframe(df)
    assert len(records) == 2
    assert all(r["report_date"] != None for r in records)  # noqa: E711
    print(f"  {len(records)} of 3 rows kept")
    print("PASS\n")


def test_non_numeric_index_values_become_nan_not_fatal():
    print("=" * 60)
    print("4. A non-numeric index value coerces to NaN instead of raising")
    print("=" * 60)
    df = _source_frame(GPRD=[101.48, "N/A", 154.97])
    records = parse_gpr_dataframe(df)
    assert len(records) == 3
    assert pd.isna(records[1]["gprd"])
    print(f"  middle row gprd: {records[1]['gprd']}")
    print("PASS\n")


def test_duplicate_dates_deduplicated():
    print("=" * 60)
    print("5. Duplicate report_date rows are deduplicated")
    print("=" * 60)
    df = _source_frame(date=["2026-08-08", "2026-08-08", "2026-08-10"])
    records = parse_gpr_dataframe(df)
    dates = [r["report_date"] for r in records]
    assert len(dates) == len(set(dates))
    print(f"  {len(records)} unique dates from 3 input rows")
    print("PASS\n")


if __name__ == "__main__":
    test_maps_uppercase_columns_and_date_to_report_date()
    test_values_match_real_sample_exactly()
    test_unparseable_rows_dropped_not_crashed_on()
    test_non_numeric_index_values_become_nan_not_fatal()
    test_duplicate_dates_deduplicated()
    print("All GPR fetcher tests passed.")
