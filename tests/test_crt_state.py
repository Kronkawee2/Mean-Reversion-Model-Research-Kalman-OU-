"""
Unit tests for analysis.smc_crt.crt_state.CRTStateEngine (Phase 2b).

Hand-constructs h1 sequences with a known Asian range + sweep baked in, and
h4-style candles for equilibrium, and asserts the exact levels/state
transitions the engine should produce. Mirrors the style of
test_smc_zone_state.py (Phase 2a).
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.smc_crt.crt_state import CRTStateEngine  # noqa: E402


def _h1_df(start, rows):
    n = len(rows)
    dt = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({
        "price_datetime": dt,
        "open_price":  [r[0] for r in rows],
        "high_price":  [r[1] for r in rows],
        "low_price":   [r[2] for r in rows],
        "close_price": [r[3] for r in rows],
    })


def test_asian_range_and_bearish_sweep():
    print("=" * 60)
    print("1. Asian range high/low computed correctly + bearish sweep of the high")
    print("=" * 60)

    rows = []
    # Day 1 Asian session 00:00-05:00 (6 bars, hours 0-5): high=110, low=95
    asian_day1 = [
        (100, 105, 100, 104),   # 00:00
        (104, 108, 103, 107),   # 01:00
        (107, 110, 106, 109),   # 02:00  <- asian high 110
        (109, 109,  97,  98),   # 03:00
        (98,   99,  95,  96),   # 04:00  <- asian low 95
        (96,  100,  95,  99),   # 05:00
    ]
    rows += asian_day1
    # London/NY hours 06:00-23:00: sweep the Asian high at hour 08:00
    # (wick above 110, close back inside <=110)
    post = []
    for h in range(6, 24):
        if h == 8:
            post.append((109, 112, 108, 109.5))  # wick above 110, closes back inside
        else:
            post.append((100, 101, 99, 100))
    rows += post

    # Day 2 Asian session starts at hour 24 (00:00 next day) -> defines expiry boundary
    asian_day2 = [
        (100, 102, 99, 101),
        (101, 102, 99.5, 100.5),
        (100.5, 103, 100, 102),
        (102, 103, 101, 101.5),
        (101.5, 102, 100, 101),
        (101, 102, 100.5, 101.5),
    ]
    rows += asian_day2
    rows += [(100, 101, 99, 100)] * 3  # a few more bars after day2 asian session

    df = _h1_df("2026-01-01 00:00", rows)
    engine = CRTStateEngine()
    signals = engine.detect_asian_sweeps(df, symbol="TEST", timeframe="h1")

    day1 = pd.Timestamp("2026-01-01").date()
    high_row = signals[(signals["signal_type"] == "asian_range_high") & (signals["session_date"] == day1)].iloc[0]
    low_row = signals[(signals["signal_type"] == "asian_range_low") & (signals["session_date"] == day1)].iloc[0]

    assert high_row["level_price"] == 110, high_row["level_price"]
    assert low_row["level_price"] == 95, low_row["level_price"]

    assert high_row["state"] == "swept", high_row["state"]
    assert high_row["sweep_direction"] == "bearish", high_row["sweep_direction"]
    assert high_row["swept_at_bar"] == df["price_datetime"].iloc[8], high_row["swept_at_bar"]

    assert low_row["state"] == "expired", low_row["state"]
    assert low_row["sweep_direction"] is None

    print(f"  [+] asian_high={high_row['level_price']} state={high_row['state']} swept_at={high_row['swept_at_bar']}")
    print(f"  [+] asian_low={low_row['level_price']} state={low_row['state']}")
    print("  [OK] test_asian_range_and_bearish_sweep PASSED\n")


def test_bullish_sweep_of_low():
    print("=" * 60)
    print("2. Bullish sweep of the Asian low")
    print("=" * 60)

    asian = [
        (100, 105, 100, 104),
        (104, 108, 103, 107),
        (107, 110, 106, 109),
        (109, 109,  97,  98),
        (98,   99,  95,  96),
        (96,  100,  95,  99),
    ]
    post = []
    for h in range(6, 24):
        if h == 10:
            post.append((96, 97, 93, 96.5))  # wick below 95, closes back inside
        else:
            post.append((100, 101, 99, 100))

    rows = asian + post
    df = _h1_df("2026-02-01 00:00", rows)
    engine = CRTStateEngine()
    signals = engine.detect_asian_sweeps(df, symbol="TEST", timeframe="h1")

    day = pd.Timestamp("2026-02-01").date()
    low_row = signals[(signals["signal_type"] == "asian_range_low") & (signals["session_date"] == day)].iloc[0]
    high_row = signals[(signals["signal_type"] == "asian_range_high") & (signals["session_date"] == day)].iloc[0]

    assert low_row["state"] == "swept"
    assert low_row["sweep_direction"] == "bullish"
    assert low_row["swept_at_bar"] == df["price_datetime"].iloc[10]
    # no next session in this short window -> high never swept, and no
    # expiry can be determined (no next session start observed)
    assert high_row["state"] == "pending", high_row["state"]
    assert high_row["expired_at_bar"] is None

    print(f"  [+] asian_low swept_at={low_row['swept_at_bar']} direction={low_row['sweep_direction']}")
    print(f"  [+] asian_high state={high_row['state']} (no next session -> stays pending)")
    print("  [OK] test_bullish_sweep_of_low PASSED\n")


def test_equilibrium():
    print("=" * 60)
    print("3. Range Equilibrium (50%) on synthetic h4 candles")
    print("=" * 60)

    dt = pd.date_range("2026-01-01", periods=4, freq="4h")
    df = pd.DataFrame({
        "price_datetime": dt,
        "open_price":  [100.0, 105.0, 98.0, 102.0],
        "high_price":  [110.0, 108.0, 100.0, 104.0],
        "low_price":   [90.0, 100.0, 90.0, 96.0],
        "close_price": [105.0, 101.0, 92.0, 103.0],
    })
    engine = CRTStateEngine()
    signals = engine.calc_equilibrium(df, symbol="TEST", timeframe="h4")

    assert len(signals) == 4
    assert (signals["signal_type"] == "equilibrium").all()

    row0 = signals.iloc[0]
    assert row0["equilibrium_price"] == 100.0, row0["equilibrium_price"]  # (110+90)/2
    assert row0["zone_bias"] == "premium", row0["zone_bias"]  # close 105 > 100

    row1 = signals.iloc[1]
    assert row1["equilibrium_price"] == 104.0  # (108+100)/2
    assert row1["zone_bias"] == "discount"  # close 101 < 104

    row2 = signals.iloc[2]
    assert row2["equilibrium_price"] == 95.0  # (100+90)/2
    assert row2["zone_bias"] == "discount"  # close 92 < 95

    row3 = signals.iloc[3]
    assert row3["equilibrium_price"] == 100.0  # (104+96)/2
    assert row3["zone_bias"] == "premium"  # close 103 > 100

    print(f"  [+] candle0 eq={row0['equilibrium_price']} bias={row0['zone_bias']}")
    print(f"  [+] candle1 eq={row1['equilibrium_price']} bias={row1['zone_bias']}")
    print("  [OK] test_equilibrium PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   CRT STATE ENGINE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_asian_range_and_bearish_sweep()
    test_bullish_sweep_of_low()
    test_equilibrium()

    print("#" * 60)
    print("   ALL CRT-STATE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
