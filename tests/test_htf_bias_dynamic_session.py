"""
Unit tests for session_weighting_mode='dynamic' (6h-bucket, sweep-driven
weighting, comparison mode vs the static clock-based mode). The critical
property to verify is causality: a bar must never be elevated by a sweep
that, from its own point in time, hasn't happened yet.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.strategies.htf_bias_engine import HTFBiasEngine  # noqa: E402

EMPTY_CRT = pd.DataFrame(columns=["bar_datetime", "zone_bias"])
EMPTY_FEAT = pd.DataFrame(columns=["bar_datetime", "ema_20", "ema_50", "ema_200", "rsi_14"])
EMPTY_VP = pd.DataFrame(columns=["session_date", "session_poc"])
EMPTY_DIV = pd.DataFrame(columns=["bar_datetime", "divergence_class", "direction"])
EMPTY_ZONES = pd.DataFrame(columns=["zone_type", "state", "created_at_bar", "invalidated_at_bar"])


def test_bucket_starts_quiet_and_elevates_only_from_sweep_bar_onward():
    print("=" * 60)
    print("1. Dynamic mode: bucket is quiet until its own sweep bar, then")
    print("   elevated from that bar onward -- never before (no look-ahead)")
    print("=" * 60)

    # 00:00-06:00 bucket, 6 bars. Sweep occurs at bar 3 (03:00).
    dt = pd.date_range("2026-01-01 00:00", periods=6, freq="h")
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100.0] * 6})
    sweeps = pd.DataFrame([{"bar_datetime": dt[3], "direction": "bullish"}])

    engine = HTFBiasEngine()
    out = engine.compute_bias(
        h1_bars, EMPTY_ZONES, EMPTY_CRT, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, sweeps,
        symbol="XAUUSD", session_weighting_mode="dynamic",
    )

    for i in range(3):
        assert out.iloc[i]["session_multiplier"] == 1.0, f"bar {i} should be quiet (pre-sweep), got {out.iloc[i]['session_multiplier']}"
        assert "quiet" in out.iloc[i]["session"]
    for i in range(3, 6):
        assert out.iloc[i]["session_multiplier"] == 1.2, f"bar {i} should be elevated (at/after sweep), got {out.iloc[i]['session_multiplier']}"
        assert "elevated" in out.iloc[i]["session"]

    print("  [+] bars 0-2 quiet (x1.0, before the sweep) -> bars 3-5 elevated (x1.2, at/after the sweep)")
    print("  [OK] test_bucket_starts_quiet_and_elevates_only_from_sweep_bar_onward PASSED\n")


def test_elevation_resets_at_next_bucket_boundary():
    print("=" * 60)
    print("2. Elevation does not carry over into the next 6h bucket")
    print("=" * 60)

    # Sweep at 05:00 (still in 00-06 bucket). Bar at 06:00 starts a NEW
    # bucket (06-12) and must reset to quiet despite the prior sweep.
    dt = pd.date_range("2026-01-01 04:00", periods=4, freq="h")  # 04,05,06,07
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100.0] * 4})
    sweeps = pd.DataFrame([{"bar_datetime": dt[1], "direction": "bullish"}])  # 05:00

    engine = HTFBiasEngine()
    out = engine.compute_bias(
        h1_bars, EMPTY_ZONES, EMPTY_CRT, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, sweeps,
        symbol="XAUUSD", session_weighting_mode="dynamic",
    )

    assert out.iloc[0]["session_multiplier"] == 1.0   # 04:00, before sweep
    assert out.iloc[1]["session_multiplier"] == 1.2   # 05:00, sweep bar
    assert out.iloc[2]["session_multiplier"] == 1.0   # 06:00, NEW bucket -> reset to quiet
    assert out.iloc[3]["session_multiplier"] == 1.0   # 07:00, still quiet (no sweep in this bucket)

    print("  [+] 04:00=quiet(x1.0) 05:00=elevated(x1.2,sweep) 06:00=quiet(x1.0,new bucket,resets) 07:00=quiet(x1.0)")
    print("  [OK] test_elevation_resets_at_next_bucket_boundary PASSED\n")


def test_static_and_dynamic_modes_agree_on_scoped_components():
    print("=" * 60)
    print("3. Both modes scale only crt_contribution/liquidity_sweep_contribution")
    print("   -- SMC/indicator/VP identical regardless of mode")
    print("=" * 60)

    dt = pd.date_range("2026-01-01 00:00", periods=3, freq="h")
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100.0] * 3})
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bullish", "state": "active",
                                "created_at_bar": dt[0], "invalidated_at_bar": None}])
    crt_equilibrium = pd.DataFrame([{"bar_datetime": dt[0], "zone_bias": "discount"}])
    sweeps = pd.DataFrame([{"bar_datetime": dt[0], "direction": "bullish"}])

    engine = HTFBiasEngine()
    out_static = engine.compute_bias(
        h1_bars, smc_zones, crt_equilibrium, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, sweeps,
        symbol="XAUUSD", session_weighting_mode="static",
    )
    out_dynamic = engine.compute_bias(
        h1_bars, smc_zones, crt_equilibrium, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, sweeps,
        symbol="XAUUSD", session_weighting_mode="dynamic",
    )

    assert (out_static["smc_contribution"] == out_dynamic["smc_contribution"]).all()
    assert (out_static["crt_contribution"] == out_dynamic["crt_contribution"]).all()  # stored unscaled in both
    assert (out_static["liquidity_sweep_contribution"] == out_dynamic["liquidity_sweep_contribution"]).all()

    print("  [+] unscaled component columns identical between modes -- only session_multiplier differs")
    print("  [OK] test_static_and_dynamic_modes_agree_on_scoped_components PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   HTF BIAS ENGINE — DYNAMIC SESSION WEIGHTING TESTS")
    print("#" * 60 + "\n")

    test_bucket_starts_quiet_and_elevates_only_from_sweep_bar_onward()
    test_elevation_resets_at_next_bucket_boundary()
    test_static_and_dynamic_modes_agree_on_scoped_components()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
