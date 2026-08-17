"""
Unit tests for analysis/backtester/deflated_sharpe.py.

Validates the statistical primitives against known reference values (not
just "does it run"): the normal CDF/PPF implementations, the DSR's core
sanity property (deflating against >1 trial produces a MORE conservative
threshold than testing against 0, so DSR <= plain PSR-vs-zero always), and
the standard trade metrics (win rate, profit factor, expectancy, max
drawdown) against a hand-computed example.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.backtester.deflated_sharpe import (  # noqa: E402
    _norm_cdf, _norm_ppf, sharpe_ratio, sample_skew, sample_kurtosis_pearson,
    probabilistic_sharpe_ratio, expected_max_sharpe, deflated_sharpe_ratio, trade_metrics,
)


def test_norm_cdf_and_ppf_match_known_values():
    print("=" * 60)
    print("1. Standard normal CDF/PPF against well-known reference values")
    print("=" * 60)

    assert abs(_norm_cdf(0.0) - 0.5) < 1e-9
    assert abs(_norm_cdf(1.959963985) - 0.975) < 1e-6
    assert abs(_norm_cdf(-1.959963985) - 0.025) < 1e-6

    assert abs(_norm_ppf(0.5) - 0.0) < 1e-6
    assert abs(_norm_ppf(0.975) - 1.959963985) < 1e-4
    assert abs(_norm_ppf(0.025) - (-1.959963985)) < 1e-4

    print("  [+] CDF(0)=0.5, CDF(1.96)~=0.975, PPF(0.975)~=1.96 -- all within tolerance")
    print("  [OK] test_norm_cdf_and_ppf_match_known_values PASSED\n")


def test_dsr_is_never_more_generous_than_plain_psr_vs_zero():
    print("=" * 60)
    print("2. Core DSR sanity property: deflating against the expected max")
    print("   Sharpe of >1 trials must NEVER produce a HIGHER (more")
    print("   favorable) significance than testing the same Sharpe against")
    print("   a plain 0 benchmark -- selection-bias correction can only")
    print("   make you more skeptical, never less")
    print("=" * 60)

    rng = np.random.default_rng(42)
    returns = rng.normal(loc=0.15, scale=1.0, size=300)  # a mildly positive, roughly-normal return stream

    result = deflated_sharpe_ratio(returns, n_trials=2, sr_variance_across_trials=0.02)
    assert result["dsr"] is not None and result["psr_vs_zero"] is not None
    assert result["dsr"] <= result["psr_vs_zero"] + 1e-9, (
        f"DSR ({result['dsr']}) must not exceed PSR-vs-zero ({result['psr_vs_zero']})"
    )
    assert result["sr0_threshold"] > 0, "with n_trials=2 and positive variance, sr0 must be > 0"

    print(f"  [+] sharpe={result['sharpe']:.3f}  sr0_threshold={result['sr0_threshold']:.3f}")
    print(f"  [+] psr_vs_zero={result['psr_vs_zero']:.4f}  dsr={result['dsr']:.4f}  (dsr <= psr_vs_zero, confirmed)")
    print("  [OK] test_dsr_is_never_more_generous_than_plain_psr_vs_zero PASSED\n")


def test_dsr_with_single_trial_reduces_to_plain_psr_vs_zero():
    print("=" * 60)
    print("3. With n_trials < 2 (no selection-bias correction to apply),")
    print("   expected_max_sharpe must be 0, so DSR reduces to plain")
    print("   PSR-vs-zero exactly")
    print("=" * 60)

    rng = np.random.default_rng(7)
    returns = rng.normal(loc=0.1, scale=1.0, size=150)

    sr0 = expected_max_sharpe(sr_variance_across_trials=0.02, n_trials=1)
    assert sr0 == 0.0, f"expected sr0=0 with n_trials=1, got {sr0}"

    result = deflated_sharpe_ratio(returns, n_trials=1, sr_variance_across_trials=0.02)
    assert abs(result["dsr"] - result["psr_vs_zero"]) < 1e-9

    print(f"  [+] n_trials=1 -> sr0_threshold=0.0 -> dsr == psr_vs_zero ({result['dsr']:.4f})")
    print("  [OK] test_dsr_with_single_trial_reduces_to_plain_psr_vs_zero PASSED\n")


def test_trade_metrics_hand_computed_example():
    print("=" * 60)
    print("4. Trade metrics (win rate, profit factor, expectancy, max")
    print("   drawdown) against a small hand-computed R-outcome sequence")
    print("=" * 60)

    # 5 trades: +2R, -1R, +0.5R, -1R, +3R (chronological order)
    r = [2.0, -1.0, 0.5, -1.0, 3.0]
    m = trade_metrics(r)

    assert m["n_trades"] == 5
    assert abs(m["win_rate"] - 3 / 5) < 1e-9  # 3 wins (2.0, 0.5, 3.0) out of 5
    # gross win = 2.0+0.5+3.0=5.5, gross loss = 1.0+1.0=2.0 -> PF=2.75
    assert abs(m["profit_factor"] - 2.75) < 1e-9
    # expectancy = mean(2,-1,0.5,-1,3) = 3.5/5 = 0.7
    assert abs(m["expectancy_r"] - 0.7) < 1e-9
    # equity curve: 2.0, 1.0, 1.5, 0.5, 3.5 -- running peak: 2,2,2,2,3.5 -- drawdown: 0,1,0.5,1.5,0 -> max=1.5
    assert abs(m["max_drawdown_r"] - 1.5) < 1e-9
    assert m["equity_curve"] == [2.0, 1.0, 1.5, 0.5, 3.5]

    print(f"  [+] win_rate={m['win_rate']}, profit_factor={m['profit_factor']}, "
          f"expectancy_r={m['expectancy_r']}, max_drawdown_r={m['max_drawdown_r']}")
    print("  [OK] test_trade_metrics_hand_computed_example PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   DEFLATED SHARPE RATIO — UNIT TESTS")
    print("#" * 60 + "\n")

    test_norm_cdf_and_ppf_match_known_values()
    test_dsr_is_never_more_generous_than_plain_psr_vs_zero()
    test_dsr_with_single_trial_reduces_to_plain_psr_vs_zero()
    test_trade_metrics_hand_computed_example()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
