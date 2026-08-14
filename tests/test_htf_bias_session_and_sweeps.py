"""
Unit tests for the Step 2/3 additions to HTFBiasEngine: liquidity sweep
component (±15, single most-recent-event read) and session-based weighting
(bounded multiplier on CRT + liquidity sweep contributions only).

Separate from test_htf_bias_engine.py, which predates these features and
neutralizes session weighting to keep its own hand-calculated numbers pure.
These tests use real session-hour timestamps deliberately, so the session
multiplier is exercised, not bypassed.
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
EMPTY_SWEEPS = pd.DataFrame(columns=["bar_datetime", "direction"])


def test_liquidity_sweep_most_recent_event_read():
    print("=" * 60)
    print("1. Liquidity sweep contributes +/-15 from its own most-recent")
    print("   event, not a sum over multiple events in the window")
    print("=" * 60)

    # 2026-01-02 is a London-hour day for these bars (07:00 start) -- use
    # hours 7-11 (london, mult=1.0) so the sweep's raw +/-15 shows unscaled.
    dt = pd.date_range("2026-01-02 07:00", periods=5, freq="h")
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100] * 5})
    # two bullish SSL sweeps: one at bar 1, one at bar 3 -- if this were
    # additive-summed (the hidden-divergence mistake), bar 3+ would show
    # +30; the correct single-most-recent-read behavior caps it at +15.
    sweeps = pd.DataFrame([
        {"bar_datetime": dt[1], "direction": "bullish"},
        {"bar_datetime": dt[3], "direction": "bullish"},
    ])

    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, EMPTY_ZONES, EMPTY_CRT, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, sweeps, symbol="XAUUSD")

    assert out.iloc[0]["liquidity_sweep_contribution"] == 0.0
    assert out.iloc[1]["liquidity_sweep_contribution"] == 15.0
    assert out.iloc[1]["liquidity_sweep_direction"] == "bullish"
    assert out.iloc[2]["liquidity_sweep_contribution"] == 15.0  # bar 1's sweep still in the 20h window
    assert out.iloc[3]["liquidity_sweep_contribution"] == 15.0  # NOT 30 -- most recent event only
    assert out.iloc[3]["confluence_score"] == 15.0

    print("  [+] bar1=+15 (first sweep), bar3=+15 (still just the most recent, not summed to +30)")
    print("  [OK] test_liquidity_sweep_most_recent_event_read PASSED\n")


def test_session_multiplier_applies_only_to_crt_and_sweep():
    print("=" * 60)
    print("2. Session multiplier scales ONLY crt_contribution and")
    print("   liquidity_sweep_contribution -- SMC/indicator/VP untouched")
    print("=" * 60)

    # Same bar (same SMC/CRT/indicator/VP/sweep inputs), three different
    # clock times -> three different session multipliers.
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bullish", "state": "active",
                                "created_at_bar": pd.Timestamp("2026-01-01 00:00"), "invalidated_at_bar": None}])

    def run_at(hour_start: str):
        dt = pd.date_range(hour_start, periods=1, freq="h")
        h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100.0]})
        crt_equilibrium = pd.DataFrame([{"bar_datetime": dt[0], "zone_bias": "discount"}])
        sweeps = pd.DataFrame([{"bar_datetime": dt[0], "direction": "bullish"}])
        smc = smc_zones.copy()
        smc["created_at_bar"] = dt[0] - pd.Timedelta(hours=1)
        engine = HTFBiasEngine()
        return engine.compute_bias(h1_bars, smc, crt_equilibrium, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, sweeps, symbol="XAUUSD").iloc[0]

    killzone = run_at("2026-01-01 13:00")  # 13:00 UTC -> killzone, mult=1.2
    london = run_at("2026-01-01 09:00")    # 09:00 UTC -> london-only, mult=1.0
    asian = run_at("2026-01-01 02:00")     # 02:00 UTC -> asian, mult=0.8

    assert killzone["session"] == "killzone" and killzone["session_multiplier"] == 1.2
    assert london["session"] == "london" and london["session_multiplier"] == 1.0
    assert asian["session"] == "asian" and asian["session_multiplier"] == 0.8

    # smc_contribution (+5, one bullish zone) is IDENTICAL across all three --
    # session weighting must not touch it.
    assert killzone["smc_contribution"] == london["smc_contribution"] == asian["smc_contribution"] == 5.0

    # crt_contribution and liquidity_sweep_contribution are stored UNSCALED
    # (both still read +15 raw in every row) -- session_multiplier is a
    # separate stored column, applied at summation time, not baked into
    # these per-component values.
    assert killzone["crt_contribution"] == london["crt_contribution"] == asian["crt_contribution"] == 15.0
    assert killzone["liquidity_sweep_contribution"] == london["liquidity_sweep_contribution"] == asian["liquidity_sweep_contribution"] == 15.0

    # raw_score_before_caution = smc(5) + crt(15)*mult + sweep(15)*mult
    # killzone: 5 + 18 + 18 = 41
    # london:   5 + 15 + 15 = 35
    # asian:    5 + 12 + 12 = 29
    assert killzone["raw_score_before_caution"] == 41.0, killzone["raw_score_before_caution"]
    assert london["raw_score_before_caution"] == 35.0, london["raw_score_before_caution"]
    assert asian["raw_score_before_caution"] == 29.0, asian["raw_score_before_caution"]

    print(f"  [+] killzone(x1.2)=41  london(x1.0)=35  asian(x0.8)=29 -- same inputs, session-scaled totals")
    print("  [OK] test_session_multiplier_applies_only_to_crt_and_sweep PASSED\n")


def test_session_boundaries_cover_all_24_hours_no_gaps():
    print("=" * 60)
    print("3. Every UTC hour 0-23 classifies into exactly one session bucket")
    print("=" * 60)
    from analysis.strategies.htf_bias_engine import classify_session, SESSION_MULTIPLIER

    counts = {"asian": 0, "london": 0, "ny": 0, "killzone": 0}
    for h in range(24):
        s = classify_session(h)
        assert s in SESSION_MULTIPLIER
        counts[s] += 1
    assert sum(counts.values()) == 24
    # killzone(12-15)=4h, london-only(7-11)=5h, ny-only(16-20)=5h, asian/off-hours(21-6)=10h
    assert counts == {"killzone": 4, "london": 5, "ny": 5, "asian": 10}, counts

    print(f"  [+] {counts} -- sums to 24, no gaps")
    print("  [OK] test_session_boundaries_cover_all_24_hours_no_gaps PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   HTF BIAS ENGINE — SESSION WEIGHTING + LIQUIDITY SWEEP TESTS")
    print("#" * 60 + "\n")

    test_liquidity_sweep_most_recent_event_read()
    test_session_multiplier_applies_only_to_crt_and_sweep()
    test_session_boundaries_cover_all_24_hours_no_gaps()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
