"""
GARCH(1,1)-filtered Ornstein-Uhlenbeck mean reversion -- the third math-
derived model tried after plain OU (kalman_mean_reversion.py) and CIR
(cir_mean_reversion.py) both failed to clear a validated edge (see
RESULTS.md experiment 19-27).

Drift term is IDENTICAL to OU and CIR: dX_t = theta*(mu - X_t)*dt + ...
Where this differs from both:
  - OU: noise variance sigma^2 is CONSTANT, re-estimated once per
    recalibration window and frozen until the next one.
  - CIR: noise variance sigma^2 * X_t depends on the current PRICE LEVEL.
  - GARCH-OU (this file): noise variance follows Bollerslev's (1986)
    GARCH(1,1) process, sigma_t^2 = omega + alpha*eps_{t-1}^2 +
    beta*sigma_{t-1}^2 -- it depends on RECENT SHOCK MAGNITUDE and
    RECENT VARIANCE, not price level. This targets volatility CLUSTERING
    (the well-documented stylized fact that large moves tend to be
    followed by large moves, of either sign, and calm periods by calm
    periods) rather than a level effect. GARCH is a genuinely solved,
    widely used econometric model (Engle 1982's ARCH, Bollerslev 1986's
    GARCH extension, part of the work behind Engle's 2003 Nobel prize in
    economics) -- not an empirical rule invented for this project.

Practical effect: entry/exit bands widen immediately after a volatility
shock and decay back down gradually (GARCH's persistence), rather than
OU's band staying flat between periodic recalibrations or CIR's band
tracking price level. Whether that's what actually helps XAUUSD/EURUSD is
exactly what this file's rolling WFO test needs to answer.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from analysis.strategies.kalman_mean_reversion import estimate_ar1, _atr, VolatilityRegimeHMM


def estimate_garch11(residuals: np.ndarray):
    """MLE fit of a GARCH(1,1) process on a residual series (here, the
    AR(1)/OU-drift residuals from estimate_ar1, NOT raw returns -- the
    volatility model sits on top of the same drift already being used).

    sigma_t^2 = omega + alpha*eps_{t-1}^2 + beta*sigma_{t-1}^2

    Returns (omega, alpha, beta). Falls back to a stationary constant-
    variance parameterization (alpha=beta=0, omega=sample variance) if
    the optimizer fails to converge to a valid (omega>0, alpha,beta>=0,
    alpha+beta<1) point -- that fallback is exactly OU's own assumption,
    so GARCH-OU degrades gracefully to plain OU when there's no
    detectable volatility clustering in the window.
    """
    eps = np.asarray(residuals, dtype=float)
    eps = eps[np.isfinite(eps)]
    n = len(eps)
    var0 = float(np.var(eps)) if n > 1 else 1e-8
    var0 = max(var0, 1e-12)
    fallback = (var0, 0.0, 0.0)
    if n < 30:
        return fallback

    def neg_log_lik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return 1e10
        sigma2 = np.empty(n)
        sigma2[0] = var0
        for t in range(1, n):
            sigma2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sigma2[t - 1]
        sigma2 = np.maximum(sigma2, 1e-12)
        ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + eps ** 2 / sigma2)
        return -ll

    x0 = np.array([var0 * 0.05, 0.10, 0.85])
    bounds = [(1e-12, None), (0.0, 0.999), (0.0, 0.999)]
    try:
        res = minimize(neg_log_lik, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 40})
        omega, alpha, beta = res.x
        if not res.success or omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return fallback
        return float(omega), float(alpha), float(beta)
    except Exception:
        return fallback


class KalmanGARCH:
    """Same recursive OU-drift structure as KalmanOU, but the noise
    variance sigma2 is a LIVE GARCH(1,1) state updated every bar from the
    Kalman filter's own innovation (z_t - predicted x_t), instead of
    being fixed for the whole inter-recalibration window."""

    def __init__(self, phi: float, mu: float, omega: float, alpha: float, beta: float,
                 sigma2_0: float, obs_noise_scale: float = 1.0, q_mult: float = 1.0):
        self.phi = phi
        self.mu = mu
        self.omega, self.alpha, self.beta = omega, alpha, beta
        self.sigma2 = max(sigma2_0, 1e-12)
        self.obs_noise_scale = max(obs_noise_scale, 0.01)
        self.q_mult = max(q_mult, 1e-6)
        self.x = mu
        self.P = self.sigma2 * self.obs_noise_scale

    def predict(self):
        x_pred = self.phi * self.x + (1 - self.phi) * self.mu
        q = self.sigma2 * max(1 - self.phi ** 2, 1e-6) * self.q_mult
        self.P = self.phi ** 2 * self.P + q
        return x_pred

    def update(self, z: float):
        x_pred = self.predict()
        eps = z - x_pred  # this bar's GARCH innovation
        r = self.sigma2 * self.obs_noise_scale
        k = self.P / (self.P + r)
        self.x = x_pred + k * (z - x_pred)
        self.P = (1 - k) * self.P
        # advance the GARCH state AFTER using this bar's sigma2 for P/R above,
        # so next bar's variance reflects this bar's realized shock.
        self.sigma2 = max(self.omega + self.alpha * eps ** 2 + self.beta * self.sigma2, 1e-12)

    @property
    def theta(self) -> float:
        return -np.log(self.phi) if 0 < self.phi < 1 else 1e-6

    @property
    def sigma_stat(self) -> float:
        """OU's stationary-std formula with the CURRENT GARCH sigma2
        plugged in -- an approximation (the true stationary distribution
        of a GARCH-diffusion hybrid has no simple closed form), but a
        standard practical simplification: treat the band width as
        tracking the LATEST estimated variance level."""
        return float(np.sqrt(self.sigma2 / max(2 * self.theta, 1e-12)))

    @property
    def half_life_bars(self) -> float:
        return np.log(2) / max(self.theta, 1e-12)


def run_garch_mean_reversion(
    bar_datetime: pd.Series,
    close: pd.Series,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    side: str = "both",
    calib_window: int = 60,
    recalib_every: int = 1,
    obs_noise_scale: float = 1.0,
    q_mult: float = 1.0,
    k: float = 1.0,
    z_stop: float | None = None,
    half_life_mult: float | None = None,
    hmm_calib_bars: int | None = None,
    hmm_block_states: tuple[int, ...] = (2,),
    tau_threshold: float | None = None,
    spread: float | None = None,
    friction_hurdle_mult: float = 2.5,
) -> pd.DataFrame:
    """GARCH-OU analogue of run_mean_reversion()/run_cir_mean_reversion()
    -- identical entry/exit/risk-control shape and output columns, so it
    plugs into the same sim_pnl()/run_cfg() helpers unmodified. Same lean
    parameter set as the CIR engine (no ATR-stop/ADX/Hurst/Wyckoff/
    trend_aware -- ports the secondary risk controls later only if this
    core diffusion-model swap shows something worth keeping).
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
    out_sigma_stat = np.full(n, np.nan)
    out_upper = np.full(n, np.nan)
    out_lower = np.full(n, np.nan)
    signals = [None] * n

    kalman = None
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
            resid = window[1:] - (phi * window[:-1] + (1 - phi) * mu)
            omega, alpha, beta = estimate_garch11(resid)
            sigma2_0 = omega / max(1 - alpha - beta, 1e-6) if (alpha + beta) < 1 else float(np.var(resid))
            prev_x = kalman.x if kalman is not None else mu
            prev_p = kalman.P if kalman is not None else None
            prev_sigma2 = kalman.sigma2 if kalman is not None else sigma2_0
            kalman = KalmanGARCH(phi, mu, omega, alpha, beta, prev_sigma2,
                                  obs_noise_scale=obs_noise_scale, q_mult=q_mult)
            if prev_p is not None:
                kalman.x, kalman.P = prev_x, prev_p

        kalman.update(closes[t])
        out_mean[t] = kalman.x
        sigma_stat = kalman.sigma_stat
        out_sigma_stat[t] = sigma_stat
        out_upper[t] = kalman.x + k * sigma_stat
        out_lower[t] = kalman.x - k * sigma_stat

        price = closes[t]
        hmm_regime = None
        if hmm is not None and t >= hmm_calib_bars and np.isfinite(hmm_vols[t]):
            hmm_regime = hmm.update(hmm_vols[t])

        if position != 0:
            bars_held += 1
            z_now = (price - out_mean[t]) / sigma_stat if sigma_stat > 0 else 0.0
            if z_stop and abs(z_now) >= z_stop:
                signals[t] = "z_stop_long" if position == 1 else "z_stop_short"
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
        "sigma_stat": out_sigma_stat,
        "upper_band": out_upper,
        "lower_band": out_lower,
        "signal": signals,
    })
