"""
Deflated Sharpe Ratio (Bailey & Lopez de Prado, "The Deflated Sharpe Ratio:
Correcting for Selection Bias, Backtest Overfitting, and Non-Normality",
2014) plus the standard trade-level backtest metrics (win rate, profit
factor, expectancy, max drawdown) that sit alongside it.

This is a fresh, additive module (analysis/backtester/backtest.py already
exists in this package from an earlier phase -- an MTFStrategyEngine-signal
backtester unrelated to the current LTF-trigger/structural-TP pipeline, and
its TP-checked-before-SL bar-resolution order is not something this module
reuses). Nothing here modifies that file.

WHY A DEFLATED, NOT PLAIN, SHARPE RATIO: a plain Sharpe ratio computed on
one strategy's own trade returns says nothing about how likely that Sharpe
is to be a statistical fluke -- especially relevant here, where we are
explicitly comparing two configurations (Mode A vs Mode B) and would
naturally be tempted to prefer whichever scores higher. The DSR corrects
for exactly that selection-bias risk (by deflating against the expected
maximum Sharpe ratio across N trials) AND for non-normal returns (via the
observed skew/kurtosis of the trade R-multiples, which are NOT normally
distributed here by construction -- wins are the trade's own structural_rr,
a right-skewed value, losses are always exactly -1R).

TWO IMPORTANT, EXPLICITLY-FLAGGED LIMITATIONS OF THIS IMPLEMENTATION:

1. N (the trial count) and V[SR_n] (the variance of Sharpe ratios across
   trials) are set to N=2 with V[SR_n] estimated from exactly two observed
   Sharpe ratios (Mode A's and Mode B's, for the same symbol, full period)
   -- see run_structural_backtest.py. This is the number of configurations
   actually being compared in this project. It is NOT a robust variance
   estimate (a 2-point sample variance is about as unstable as a variance
   estimate can be) and it does NOT count every implicit researcher degree
   of freedom exercised earlier in this project (STRUCTURAL_TP_FRACTION=
   0.85, MIN_RISK_ATR_MULTIPLE=0.5, CONFIRMATION_WINDOW_BARS=20, etc. were
   all fixed by structural/causal reasoning rather than grid-searched, so
   they are not counted as separate "trials" here -- but they are still
   researcher choices, and a fully rigorous accounting would treat the
   effective N as higher than 2). Treat the reported DSR as an OPTIMISTIC
   upper bound on statistical significance, not a precise value.

2. The Sharpe ratio here is computed directly on the per-trade R-multiple
   series (mean/std of R outcomes), NOT time-annualized. Trades have
   irregular holding periods (no fixed bars-per-trade), so there is no
   single defensible annualization factor without introducing yet another
   assumption. This is a "per-trade" Sharpe, consistent with T = number of
   trades in every formula below -- not comparable to a daily-return Sharpe
   from a different kind of strategy.
"""

import math

import numpy as np


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF via scipy (falls back to a self-contained
    rational approximation -- Acklam's algorithm, ~1e-9 accuracy -- if scipy
    is unavailable, so this module has no hard runtime dependency)."""
    try:
        from scipy.stats import norm
        return float(norm.ppf(p))
    except ImportError:
        return _norm_ppf_acklam(p)


def _norm_ppf_acklam(p: float) -> float:
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"p must be in (0,1), got {p}")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
            ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def sample_skew(x: np.ndarray) -> float:
    """Bias-corrected (Fisher-Pearson) sample skewness -- matches scipy.stats.skew(bias=False)."""
    n = len(x)
    if n < 3:
        return 0.0
    mean = x.mean()
    m2 = np.mean((x - mean) ** 2)
    m3 = np.mean((x - mean) ** 3)
    if m2 <= 0:
        return 0.0
    g1 = m3 / m2 ** 1.5
    return float(math.sqrt(n * (n - 1)) / (n - 2) * g1)


def sample_kurtosis_pearson(x: np.ndarray) -> float:
    """Bias-corrected excess kurtosis, converted to the Pearson convention
    (normal distribution = 3.0), matching scipy.stats.kurtosis(fisher=False, bias=False)."""
    n = len(x)
    if n < 4:
        return 3.0
    mean = x.mean()
    m2 = np.mean((x - mean) ** 2)
    m4 = np.mean((x - mean) ** 4)
    if m2 <= 0:
        return 3.0
    g2 = m4 / m2 ** 2 - 3.0
    excess_corrected = ((n + 1) * g2 + 6) * (n - 1) / ((n - 2) * (n - 3))
    return float(excess_corrected + 3.0)


def sharpe_ratio(returns: np.ndarray) -> float:
    """Per-trade (not time-annualized) Sharpe: mean(R) / std(R), sample std (ddof=1)."""
    returns = np.asarray(returns, dtype=float)
    if len(returns) < 2:
        return 0.0
    std = returns.std(ddof=1)
    if std <= 0:
        return 0.0
    return float(returns.mean() / std)


def probabilistic_sharpe_ratio(sr_hat: float, sr_star: float, T: int, skew: float, kurt: float) -> float:
    """
    PSR(SR*) -- probability the TRUE Sharpe ratio exceeds sr_star, given an
    observed Sharpe sr_hat over T observations with the given (bias-
    corrected) skew and Pearson-convention kurtosis (normal=3).
    """
    if T < 2:
        return 0.0
    denom = 1 - skew * sr_hat + ((kurt - 1) / 4.0) * sr_hat ** 2
    denom = max(denom, 1e-12)  # guard against a degenerate/negative radicand on tiny/odd samples
    z = (sr_hat - sr_star) * math.sqrt(T - 1) / math.sqrt(denom)
    return _norm_cdf(z)


EULER_MASCHERONI = 0.5772156649015329


def expected_max_sharpe(sr_variance_across_trials: float, n_trials: int) -> float:
    """
    SR0 -- the Sharpe ratio expected to be the MAXIMUM observed across
    n_trials independent trials purely by chance, given the variance of
    Sharpe ratios across those trials. This is the benchmark the DSR tests
    the observed Sharpe against, instead of testing against 0 (which is
    what plain PSR does, and which ignores that we picked the best-looking
    of >1 configuration).
    """
    if n_trials < 2 or sr_variance_across_trials <= 0:
        return 0.0
    term1 = (1 - EULER_MASCHERONI) * _norm_ppf(1 - 1.0 / n_trials)
    term2 = EULER_MASCHERONI * _norm_ppf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(sr_variance_across_trials) * (term1 + term2)


def deflated_sharpe_ratio(returns: np.ndarray, n_trials: int, sr_variance_across_trials: float) -> dict:
    """
    Full DSR computation for one strategy's trade-return series.
    Returns a dict with sharpe (plain), sr0_threshold (the deflation
    benchmark), dsr (= PSR(sr0), the corrected significance), psr_vs_zero
    (plain PSR against 0, for reference/comparison), skew, kurtosis, n.
    """
    returns = np.asarray(returns, dtype=float)
    T = len(returns)
    if T < 2:
        return {"sharpe": None, "dsr": None, "psr_vs_zero": None, "sr0_threshold": None,
                "skew": None, "kurtosis": None, "n": T}

    sr_hat = sharpe_ratio(returns)
    skew = sample_skew(returns)
    kurt = sample_kurtosis_pearson(returns)
    sr0 = expected_max_sharpe(sr_variance_across_trials, n_trials)
    dsr = probabilistic_sharpe_ratio(sr_hat, sr0, T, skew, kurt)
    psr_vs_zero = probabilistic_sharpe_ratio(sr_hat, 0.0, T, skew, kurt)

    return {"sharpe": sr_hat, "dsr": dsr, "psr_vs_zero": psr_vs_zero, "sr0_threshold": sr0,
            "skew": skew, "kurtosis": kurt, "n": T}


def trade_metrics(r_outcomes) -> dict:
    """
    Win rate, profit factor, expectancy (mean R), max drawdown (peak-to-
    trough of the cumulative-R equity curve, in R), and the equity curve
    itself, computed over a sequence of per-trade R outcomes in
    chronological (entry/exit) order. Wins carry the trade's OWN
    structural_rr, losses are always exactly -1.0 R by construction (the
    stop defines 1R) -- never a fixed assumed R:R.
    """
    r = np.asarray(r_outcomes, dtype=float)
    n = len(r)
    if n == 0:
        return {"n_trades": 0, "win_rate": None, "profit_factor": None,
                "expectancy_r": None, "max_drawdown_r": None, "equity_curve": []}

    wins = r[r > 0]
    losses = r[r <= 0]
    win_rate = len(wins) / n
    gross_win = float(wins.sum())
    gross_loss = float(-losses.sum())
    if gross_loss > 0:
        profit_factor = gross_win / gross_loss
    else:
        profit_factor = float("inf") if gross_win > 0 else None
    expectancy = float(r.mean())

    equity = np.cumsum(r)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    max_dd = float(drawdown.max())

    return {"n_trades": n, "win_rate": win_rate, "profit_factor": profit_factor,
            "expectancy_r": expectancy, "max_drawdown_r": max_dd, "equity_curve": equity.tolist()}
