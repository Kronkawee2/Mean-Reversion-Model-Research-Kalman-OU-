"""
Unit tests for analysis.strategies.htf_bias_engine (Phase 3a).

Hand-constructs small scenarios where every component's contribution can
be computed by hand from the documented weights (SMC ±30 dominant, CRT
±15, indicator ±20, volume profile ±10, hidden divergence +12/signal
additive, regular divergence 0.85^count multiplicative caution), and
asserts the engine's confluence_score/bias match exactly. Also covers the
zone-causality bug this test suite caught during development: a zone
whose FINAL state is 'invalidated' must still count for its genuine
active/mitigated lifetime before that invalidation, not be excluded
outright.
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analysis.strategies.htf_bias_engine as hbe  # noqa: E402
from analysis.strategies.htf_bias_engine import HTFBiasEngine  # noqa: E402

EMPTY_CRT = pd.DataFrame(columns=["bar_datetime", "zone_bias"])
EMPTY_FEAT = pd.DataFrame(columns=["bar_datetime", "ema_20", "ema_50", "ema_200", "rsi_14"])
EMPTY_VP = pd.DataFrame(columns=["session_date", "session_poc"])
EMPTY_DIV = pd.DataFrame(columns=["bar_datetime", "divergence_class", "direction"])
EMPTY_ZONES = pd.DataFrame(columns=["zone_type", "state", "created_at_bar", "invalidated_at_bar"])
EMPTY_SWEEPS = pd.DataFrame(columns=["bar_datetime", "direction"])

# These tests predate session weighting and hand-verify pure component
# arithmetic (SMC/CRT/indicator/VP/divergence) independent of it. Neutralize
# the session multiplier here so those numbers stay exactly as documented;
# session weighting itself is covered separately in
# test_htf_bias_session_and_sweeps.py with real session-hour scenarios.
hbe.SESSION_MULTIPLIER = {"killzone": 1.0, "london": 1.0, "ny": 1.0, "asian": 1.0}


def _dt(n=10, start="2026-01-01 00:00"):
    return pd.date_range(start, periods=n, freq="h")


def test_full_worked_bullish_scenario():
    print("=" * 60)
    print("1. Full worked bullish scenario: hand-calculated component sums")
    print("=" * 60)

    dt = _dt()
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    # One bullish order block active for the whole window: smc = +1*5 = +5
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bullish", "state": "active",
                                "created_at_bar": dt[0], "invalidated_at_bar": None}])
    # discount -> +15
    crt_equilibrium = pd.DataFrame([{"bar_datetime": dt[0], "zone_bias": "discount"}])
    # full bullish EMA stack (105>103>100) + RSI 60>55 -> +15+5 = +20
    features_h1 = pd.DataFrame([{"bar_datetime": dt[0], "ema_20": 105, "ema_50": 103, "ema_200": 100, "rsi_14": 60}])
    # session POC = 102: bars with close<=102 -> -10, close>102 -> +10
    volume_profile = pd.DataFrame([{"session_date": dt[0].date(), "session_poc": 102}])

    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, smc_zones, crt_equilibrium, features_h1, volume_profile, EMPTY_DIV, EMPTY_SWEEPS, symbol="XAUUSD")

    # bars 0-2 (close 100,101,102 <= POC): 5+15+20-10 = 30 -> neutral (below +50 threshold)
    for i in range(3):
        assert out.iloc[i]["confluence_score"] == 30.0, out.iloc[i]["confluence_score"]
        assert out.iloc[i]["bias"] == "neutral"
    # bars 3-9 (close > POC): 5+15+20+10 = 50 -> bullish (at threshold)
    for i in range(3, 10):
        assert out.iloc[i]["confluence_score"] == 50.0, out.iloc[i]["confluence_score"]
        assert out.iloc[i]["bias"] == "bullish"

    assert (out["smc_contribution"] == 5.0).all()
    assert (out["smc_active_bullish_zones"] == 1).all()
    assert (out["crt_contribution"] == 15.0).all()
    assert (out["indicator_contribution"] == 20.0).all()

    print(f"  [+] bars 0-2: score=30 (neutral, below +50)  bars 3-9: score=50 (bullish, at threshold)")
    print("  [OK] test_full_worked_bullish_scenario PASSED\n")


def test_full_worked_bearish_scenario():
    print("=" * 60)
    print("2. Full worked bearish scenario (mirror of test 1)")
    print("=" * 60)

    dt = _dt()
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [109, 108, 107, 106, 105, 104, 103, 102, 101, 100]})
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bearish", "state": "active",
                                "created_at_bar": dt[0], "invalidated_at_bar": None}])
    crt_equilibrium = pd.DataFrame([{"bar_datetime": dt[0], "zone_bias": "premium"}])
    features_h1 = pd.DataFrame([{"bar_datetime": dt[0], "ema_20": 100, "ema_50": 103, "ema_200": 105, "rsi_14": 40}])
    volume_profile = pd.DataFrame([{"session_date": dt[0].date(), "session_poc": 102}])

    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, smc_zones, crt_equilibrium, features_h1, volume_profile, EMPTY_DIV, EMPTY_SWEEPS, symbol="XAUUSD")

    # -5 (smc) -15 (crt) -20 (indicator: full bearish stack + rsi<45) = -40 baseline;
    # close sequence is 109..100 (descending), POC=102 -- close > 102 for
    # bars 0-6 (109..103), so vp=+10 there -> total -30 -> neutral. close
    # <= 102 from bar 7 onward (102,101,100) -> vp=-10 -> total -50 -> bearish.
    for i in range(7):
        assert out.iloc[i]["confluence_score"] == -30.0, out.iloc[i]["confluence_score"]
        assert out.iloc[i]["bias"] == "neutral"
    for i in range(7, 10):
        assert out.iloc[i]["confluence_score"] == -50.0, out.iloc[i]["confluence_score"]
        assert out.iloc[i]["bias"] == "bearish"

    print(f"  [+] bars 0-6: score=-30 (neutral)  bars 7-9: score=-50 (bearish, at threshold)")
    print("  [OK] test_full_worked_bearish_scenario PASSED\n")


def test_hidden_divergence_reinforces_additively():
    print("=" * 60)
    print("3. Hidden divergence reinforces the score additively, own direction")
    print("=" * 60)

    dt = _dt()
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bullish", "state": "active",
                                "created_at_bar": dt[0], "invalidated_at_bar": None}])
    crt_equilibrium = pd.DataFrame([{"bar_datetime": dt[0], "zone_bias": "discount"}])
    features_h1 = pd.DataFrame([{"bar_datetime": dt[0], "ema_20": 105, "ema_50": 103, "ema_200": 100, "rsi_14": 60}])
    volume_profile = pd.DataFrame([{"session_date": dt[0].date(), "session_poc": 102}])
    # hidden bullish divergence confirmed at bar 6 -> +12 from bar 6 onward
    divergence_h1 = pd.DataFrame([{"bar_datetime": dt[6], "divergence_class": "hidden", "direction": "bullish"}])

    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, smc_zones, crt_equilibrium, features_h1, volume_profile, divergence_h1, EMPTY_SWEEPS, symbol="XAUUSD")

    # before the hidden signal (bars 3-5): baseline 50, unaffected
    for i in range(3, 6):
        assert out.iloc[i]["confluence_score"] == 50.0, out.iloc[i]["confluence_score"]
        assert out.iloc[i]["hidden_divergence_count"] == 0
    # from bar 6 onward: 50 + 12 = 62
    for i in range(6, 10):
        assert out.iloc[i]["confluence_score"] == 62.0, out.iloc[i]["confluence_score"]
        assert out.iloc[i]["hidden_divergence_contribution"] == 12.0
        assert out.iloc[i]["hidden_divergence_count"] == 1
        assert out.iloc[i]["bias"] == "bullish"

    print(f"  [+] bars 3-5: score=50 (no hidden signal yet)  bars 6-9: score=62 (50 + hidden +12)")
    print("  [OK] test_hidden_divergence_reinforces_additively PASSED\n")


def test_regular_divergence_dampens_multiplicatively():
    print("=" * 60)
    print("4. Regular divergence dampens the WHOLE score multiplicatively,")
    print("   pulling a bullish read down to neutral -- not a competing vote")
    print("=" * 60)

    dt = _dt()
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]})
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bullish", "state": "active",
                                "created_at_bar": dt[0], "invalidated_at_bar": None}])
    crt_equilibrium = pd.DataFrame([{"bar_datetime": dt[0], "zone_bias": "discount"}])
    features_h1 = pd.DataFrame([{"bar_datetime": dt[0], "ema_20": 105, "ema_50": 103, "ema_200": 100, "rsi_14": 60}])
    volume_profile = pd.DataFrame([{"session_date": dt[0].date(), "session_poc": 102}])
    # two regular (bearish) divergences confirmed at bars 6 and 7
    divergence_h1 = pd.DataFrame([
        {"bar_datetime": dt[6], "divergence_class": "regular", "direction": "bearish"},
        {"bar_datetime": dt[7], "divergence_class": "regular", "direction": "bearish"},
    ])

    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, smc_zones, crt_equilibrium, features_h1, volume_profile, divergence_h1, EMPTY_SWEEPS, symbol="XAUUSD")

    assert out.iloc[5]["confluence_score"] == 50.0 and out.iloc[5]["bias"] == "bullish"
    # bar 6: raw 50 * 0.85^1 = 42.5 -> below +50 -> neutral
    assert out.iloc[6]["confluence_score"] == 42.5, out.iloc[6]["confluence_score"]
    assert out.iloc[6]["regular_divergence_caution_factor"] == 0.85
    assert out.iloc[6]["bias"] == "neutral"
    # bar 7+: raw 50 * 0.85^2 = 36.125 -> rounds to 36.12 -> still neutral
    assert out.iloc[7]["confluence_score"] == 36.12, out.iloc[7]["confluence_score"]
    assert out.iloc[7]["regular_divergence_caution_factor"] == 0.7225
    assert out.iloc[7]["bias"] == "neutral"
    # raw_score_before_caution stays 50 throughout -- caution reduces the
    # FINAL score, it doesn't touch the pre-caution component sum
    assert (out["raw_score_before_caution"].iloc[3:] == 50.0).all()

    print(f"  [+] bar5=50(bullish) -> bar6=42.5(neutral, 1 caution hit) -> bar7=36.12(neutral, 2 hits)")
    print("  [OK] test_regular_divergence_dampens_multiplicatively PASSED\n")


def test_zone_causality_no_lookahead():
    print("=" * 60)
    print("5. Bug-catcher: an eventually-invalidated zone must still count for")
    print("   its genuine active/mitigated lifetime, and stop exactly at invalidation")
    print("=" * 60)

    dt = _dt()
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100] * 10})
    # zone created at bar 3, invalidated at bar 7 -- its FINAL state is
    # 'invalidated', but it was genuinely active from bar 3 through bar 6.
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bullish", "state": "invalidated",
                                "created_at_bar": dt[3], "invalidated_at_bar": dt[7]}])

    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, smc_zones, EMPTY_CRT, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, EMPTY_SWEEPS, symbol="XAUUSD")

    assert (out["smc_active_bullish_zones"].iloc[0:3] == 0).all(), "must not count before creation"
    assert (out["smc_active_bullish_zones"].iloc[3:7] == 1).all(), "must count during its active/mitigated lifetime"
    assert (out["smc_active_bullish_zones"].iloc[7:10] == 0).all(), "must stop counting at invalidation, not after"

    print(f"  [+] zone counts: 0 (bars 0-2) -> 1 (bars 3-6) -> 0 (bars 7-9), despite state='invalidated'")
    print("  [OK] test_zone_causality_no_lookahead PASSED\n")


def test_zone_recency_window_expires_uninvalidated_zones():
    print("=" * 60)
    print("5b. A zone that's NEVER invalidated still stops counting after")
    print("    SMC_ZONE_RECENCY_WINDOW_BARS hours -- added after a 2-year")
    print("    real-data audit found unbounded counting saturates the +/-30")
    print("    cap permanently in a sustained one-directional market")
    print("=" * 60)

    from analysis.strategies.htf_bias_engine import SMC_ZONE_RECENCY_WINDOW_BARS
    created = pd.Timestamp("2026-01-01 00:00")
    # sample points straddling the recency cutoff -- doesn't need every
    # hour in between, the engine only needs bar_times at the timestamps
    # actually being evaluated.
    dt = pd.DatetimeIndex([
        created,
        created + pd.Timedelta(hours=1),
        created + pd.Timedelta(hours=SMC_ZONE_RECENCY_WINDOW_BARS - 1),  # last bar still within window
        created + pd.Timedelta(hours=SMC_ZONE_RECENCY_WINDOW_BARS),      # exactly at cutoff -- must stop
        created + pd.Timedelta(hours=SMC_ZONE_RECENCY_WINDOW_BARS + 1),
    ])
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100] * len(dt)})
    # never invalidated -- the ONLY thing that should stop it counting is the recency window
    smc_zones = pd.DataFrame([{"zone_type": "order_block_bullish", "state": "active",
                                "created_at_bar": created, "invalidated_at_bar": None}])

    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, smc_zones, EMPTY_CRT, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, EMPTY_SWEEPS, symbol="XAUUSD")

    assert list(out["smc_active_bullish_zones"]) == [1, 1, 1, 0, 0], list(out["smc_active_bullish_zones"])

    print(f"  [+] counted through hour {SMC_ZONE_RECENCY_WINDOW_BARS - 1}, stopped exactly at hour {SMC_ZONE_RECENCY_WINDOW_BARS} despite never being invalidated")
    print("  [OK] test_zone_recency_window_expires_uninvalidated_zones PASSED\n")


def test_empty_inputs_produce_neutral_with_zero_contributions():
    print("=" * 60)
    print("6. No data at all -> neutral, all contributions zero (not an error)")
    print("=" * 60)

    dt = _dt(5)
    h1_bars = pd.DataFrame({"price_datetime": dt, "close_price": [100, 101, 100, 99, 100]})
    engine = HTFBiasEngine()
    out = engine.compute_bias(h1_bars, EMPTY_ZONES, EMPTY_CRT, EMPTY_FEAT, EMPTY_VP, EMPTY_DIV, EMPTY_SWEEPS, symbol="XAUUSD")

    assert len(out) == 5
    assert (out["bias"] == "neutral").all()
    assert (out["confluence_score"] == 0.0).all()

    print("  [+] all 5 bars: neutral, score=0")
    print("  [OK] test_empty_inputs_produce_neutral_with_zero_contributions PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   HTF BIAS ENGINE — UNIT TESTS")
    print("#" * 60 + "\n")

    test_full_worked_bullish_scenario()
    test_full_worked_bearish_scenario()
    test_hidden_divergence_reinforces_additively()
    test_regular_divergence_dampens_multiplicatively()
    test_zone_causality_no_lookahead()
    test_zone_recency_window_expires_uninvalidated_zones()
    test_empty_inputs_produce_neutral_with_zero_contributions()

    print("#" * 60)
    print("   ALL HTF BIAS ENGINE TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
