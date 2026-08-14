"""
Unit test for the get_rates_incremental() truncation-direction fix in
mt5_data_fetcher.py. Doesn't need a live MT5 connection -- monkeypatches
get_rates() to return a synthetic oversized range and asserts the method
keeps the OLDEST `count` bars, not the newest.

Root-cause bug this catches: the old code did `df.tail(count)` when the
fetched range exceeded `count` rows, silently and permanently dropping the
older portion of a large gap (since the sync service's next cycle uses the
returned max timestamp as its new starting point and never revisits the
dropped range). Found via a real ~88.5h outage that produced ~1062 missing
M5 bars: M5 (>500 bars over that span) got truncated and permanently lost
~562 bars, while M15/H1 (under 500 bars over the same span) were unaffected.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sync.mt5_data_fetcher import MT5DataFetcher  # noqa: E402


def _synthetic_rates(n, start="2026-08-07 23:55:00", freq="5min"):
    dt = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({
        "time": (dt.view("int64") // 10**9),
        "time_utc": dt,
        "open": [4000.0] * n, "high": [4001.0] * n, "low": [3999.0] * n, "close": [4000.5] * n,
        "tick_volume": [10] * n, "spread": [1] * n, "real_volume": [0] * n,
    })


def test_incremental_keeps_oldest_bars_when_gap_exceeds_count():
    print("=" * 60)
    print("1. get_rates_incremental keeps the OLDEST `count` bars when the")
    print("   full gap exceeds count -- not the newest (the fixed bug)")
    print("=" * 60)

    fetcher = MT5DataFetcher()
    # simulate a gap with 1062 missing M5 bars (matches the real m5 gap),
    # count=500 -> old code kept the LAST 500 (newest), permanently
    # dropping the first ~562; fixed code must keep the FIRST 500 (oldest).
    full_range = _synthetic_rates(1062)
    fetcher.get_rates = lambda *a, **k: full_range
    fetcher._drop_incomplete = lambda df, tf, include_incomplete: df

    out = fetcher.get_rates_incremental("XAUUSD", "M5", "2026-08-07T23:00:00Z", count=500)

    assert len(out) == 500
    assert out["time_utc"].iloc[0] == full_range["time_utc"].iloc[0], "must start at the OLDEST bar in the range"
    assert out["time_utc"].iloc[-1] == full_range["time_utc"].iloc[499], "must be the first 500, not the last 500"
    assert out["time_utc"].iloc[-1] != full_range["time_utc"].iloc[-1], "must NOT be the newest bar (that's the old bug)"

    print(f"  [+] kept bars {out['time_utc'].iloc[0]} -> {out['time_utc'].iloc[-1]} (oldest 500 of 1062), not the newest 500")
    print("  [OK] test_incremental_keeps_oldest_bars_when_gap_exceeds_count PASSED\n")


def test_incremental_returns_everything_when_under_count():
    print("=" * 60)
    print("2. When the gap fits under `count`, nothing is dropped (matches")
    print("   the observed M15/H1 behavior over the same real outage)")
    print("=" * 60)

    fetcher = MT5DataFetcher()
    small_range = _synthetic_rates(354, freq="15min")  # M15-equivalent bar count for the same real outage
    fetcher.get_rates = lambda *a, **k: small_range
    fetcher._drop_incomplete = lambda df, tf, include_incomplete: df

    out = fetcher.get_rates_incremental("XAUUSD", "M15", "2026-08-07T23:00:00Z", count=500)

    assert len(out) == 354
    assert out["time_utc"].iloc[-1] == small_range["time_utc"].iloc[-1]

    print("  [+] all 354 bars returned, none dropped")
    print("  [OK] test_incremental_returns_everything_when_under_count PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   MT5DataFetcher.get_rates_incremental — TRUNCATION FIX TESTS")
    print("#" * 60 + "\n")

    test_incremental_keeps_oldest_bars_when_gap_exceeds_count()
    test_incremental_returns_everything_when_under_count()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
