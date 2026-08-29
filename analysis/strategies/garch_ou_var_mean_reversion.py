"""
GARCH-OU with VaR (empirical-quantile) entry/stop thresholds, instead of
the parametric k*sigma_stat / z_stop*sigma_stat bands used by
garch_ou_mean_reversion.py. Same drift, same GARCH(1,1) variance state --
the only change is how "far enough from the mean to be abnormal" is
defined:

  k*sigma (parametric):  assumes the OU residual is ~Normal, so "k standard
    deviations away" maps to a fixed theoretical percentile (e.g. k=2.2 ->
    ~98.6th percentile under Normality).

  VaR / empirical quantile (this file): reads the percentile directly off
  the ACTUAL residual distribution observed in the calibration window, no
  Normality assumption. Entry band = the entry_pctile-th percentile of
  recent residuals (e.g. 90th/10th); stop band = the stop_pctile-th
  percentile (e.g. 99th/1st), interpreted as "the tail broke past what the
  recent empirical distribution has ever done -> treat as a regime
  break, exit." This is standard quantile-based VaR, not an invented rule.
"""

import numpy as np
import pandas as pd

from analysis.strategies.kalman_mean_reversion import estimate_ar1, VolatilityRegimeHMM
from analysis.strategies.garch_ou_mean_reversion import estimate_garch11, KalmanGARCH


def run_garch_var_mean_reversion(
    bar_datetime: pd.Series,
    close: pd.Series,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    side: str = "both",
    calib_window: int = 60,
    recalib_every: int = 1,
    obs_noise_scale: float = 1.0,
    q_mult: float = 1.0,
    entry_pctile: float = 90.0,
    stop_pctile: float | None = 99.0,
    half_life_mult: float | None = None,
    hmm_calib_bars: int | None = None,
    hmm_block_states: tuple[int, ...] = (2,),
    tau_threshold: float | None = None,
    spread: float | None = None,
    friction_hurdle_mult: float = 2.5,
) -> pd.DataFrame:
    """Same KalmanGARCH mean/variance state as run_garch_mean_reversion(),
    but entry/stop bands come from empirical quantiles of the residuals in
    the current calibration window rather than k*sigma_stat. entry_pctile
    (e.g. 90) sets the upper band at the entry_pctile-th percentile of
    residuals and the lower band at the (100-entry_pctile)-th percentile
    -- asymmetric skew in the residual distribution is preserved, unlike
    the symmetric k*sigma bands. stop_pctile works the same way one level
    further into the tail (e.g. 99/1); None disables the stop.
    """
    if side not in ("both", "long_only", "short_only"):
        raise ValueError(f"side must be 'both'/'long_only'/'short_only', got {side!r}")

    n = len(close)
    closes = close.to_numpy(dtype=float)
    highs = high.to_numpy(dtype=float) if high is not None else None
    lows = low.to_numpy(dtype=float) if low is not None else None

    hmm = None
    hmm_vols = None
    if hmm_calib_bars and highs is not None:
        hmm_vols = np.where(closes > 0, (highs - lows) / closes, np.nan)
        hmm = VolatilityRegimeHMM()
        hmm.calibrate(hmm_vols[:hmm_calib_bars])

    out_mean = np.full(n, np.nan)
    out_upper = np.full(n, np.nan)
    out_lower = np.full(n, np.nan)
    out_stop_upper = np.full(n, np.nan)
    out_stop_lower = np.full(n, np.nan)
    signals = [None] * n

    kalman = None
    resid_window = None
    position = 0
    entry_price = None
    bars_held = 0

    for t in range(n):
        if t < calib_window:
            continue
        if kalman is None or (t - calib_window) % recalib_every == 0:
            params = estimate_ar1(closes[t - calib_window:t])
            if params is None:
                continue
            phi, mu, _sigma_ou = params
            window = closes[t - calib_window:t]
            resid_window = window[1:] - (phi * window[:-1] + (1 - phi) * mu)
            omega, alpha, beta = estimate_garch11(resid_window)
            sigma2_0 = omega / max(1 - alpha - beta, 1e-6) if (alpha + beta) < 1 else float(np.var(resid_window))
            prev_x = kalman.x if kalman is not None else mu
            prev_p = kalman.P if kalman is not None else None
            prev_sigma2 = kalman.sigma2 if kalman is not None else sigma2_0
            kalman = KalmanGARCH(phi, mu, omega, alpha, beta, prev_sigma2,
                                  obs_noise_scale=obs_noise_scale, q_mult=q_mult)
            if prev_p is not None:
                kalman.x, kalman.P = prev_x, prev_p

        kalman.update(closes[t])
        out_mean[t] = kalman.x

        q_hi = np.percentile(resid_window, entry_pctile)
        q_lo = np.percentile(resid_window, 100 - entry_pctile)
        out_upper[t] = kalman.x + q_hi
        out_lower[t] = kalman.x + q_lo
        if stop_pctile is not None:
            out_stop_upper[t] = kalman.x + np.percentile(resid_window, stop_pctile)
            out_stop_lower[t] = kalman.x + np.percentile(resid_window, 100 - stop_pctile)

        price = closes[t]
        hmm_regime = None
        if hmm is not None and t >= hmm_calib_bars and np.isfinite(hmm_vols[t]):
            hmm_regime = hmm.update(hmm_vols[t])

        if position != 0:
            bars_held += 1
            if stop_pctile is not None and (price >= out_stop_upper[t] or price <= out_stop_lower[t]):
                signals[t] = "var_stop_long" if position == 1 else "var_stop_short"
                position, entry_price, bars_held = 0, None, 0
                continue
            if half_life_mult and bars_held > half_life_mult * kalman.half_life_bars:
                signals[t] = "time_stop_long" if position == 1 else "time_stop_short"
                position, entry_price, bars_held = 0, None, 0
                continue
            if position == 1 and price >= out_mean[t]:
                signals[t] = "close_long"
                position, entry_price, bars_held = 0, None, 0
                continue
            if position == -1 and price <= out_mean[t]:
                signals[t] = "close_short"
                position, entry_price, bars_held = 0, None, 0
                continue

        if position == 0:
            regime_blocked = (
                (hmm_regime is not None and hmm_regime in hmm_block_states)
                or (tau_threshold is not None and kalman.half_life_bars > tau_threshold)
                or (spread is not None and abs(price - out_mean[t]) < friction_hurdle_mult * spread)
            )
            if regime_blocked:
                continue
            if side != "long_only" and price > out_upper[t]:
                position, entry_price, bars_held = -1, price, 0
                signals[t] = "short"
            elif side != "short_only" and price < out_lower[t]:
                position, entry_price, bars_held = 1, price, 0
                signals[t] = "long"

    return pd.DataFrame({
        "bar_datetime": bar_datetime.to_numpy(),
        "close": closes,
        "mean_level": out_mean,
        "upper_band": out_upper,
        "lower_band": out_lower,
        "signal": signals,
    })
