"""
Cox-Ingersoll-Ross (CIR) mean reversion -- the same family as
kalman_mean_reversion.py's Ornstein-Uhlenbeck engine, but solving a
different stochastic differential equation:

    dX_t = theta*(mu - X_t)*dt + sigma*sqrt(X_t)*dW_t

The drift term (the "pull back toward mu at speed theta" part) is
IDENTICAL to OU. The only difference is the diffusion term: OU's noise has
constant variance sigma^2 regardless of the current price level; CIR's
noise variance scales with the current level itself (sigma^2 * X_t). This
was proposed as a candidate after OU showed no validated edge on any
tested symbol/timeframe (see RESULTS.md experiment 19-22) -- CIR is a
genuine alternative closed-form solved model (used in interest-rate
modeling, where it also guarantees X_t stays non-negative, unlike OU),
not an empirical rule like the Donchian breakout that got dropped for not
being math-derived (RESULTS.md experiment 23-24).

Practical effect: bands widen automatically when price is high and
tighten when price is low, rather than the constant-width band OU uses at
all price levels. Whether that's a better description of how XAUUSD/
EURUSD actually behave is exactly what needs testing here.

Everything downstream of theta and mu (half-life, entry/exit bands, risk
stops) reuses the exact same reasoning as the OU engine -- only the
variance estimation and the Kalman Q/R terms change to be level-dependent
instead of constant. estimate_ar1(), _atr(), and VolatilityRegimeHMM are
reused directly from kalman_mean_reversion.py rather than duplicated,
since the drift/regime-filtering logic doesn't change between the two
models.
"""

import numpy as np
import pandas as pd

from analysis.strategies.kalman_mean_reversion import estimate_ar1, _atr, VolatilityRegimeHMM


def estimate_cir_sigma(closes: np.ndarray, phi: float, mu: float) -> float:
    """CIR diffusion coefficient sigma^2, via conditional least squares on
    the same AR(1) residuals estimate_ar1() would have produced: under
    the CIR discretization, Var(resid_t) = sigma^2 * X_{t-1} (unlike OU's
    constant variance), so sigma^2 = mean(resid_t^2 / X_{t-1}) is the
    method-of-moments estimator (Chan/Karolyi/Longstaff/Sanders 1992's
    conditional least squares approach to the CIR/CKLS family)."""
    y = np.asarray(closes, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 5:
        return 1e-9
    x_lag, x_curr = y[:-1], y[1:]
    resid = x_curr - (phi * x_lag + (1 - phi) * mu)
    ratio = resid ** 2 / np.maximum(x_lag, 1e-9)
    sigma2 = float(np.mean(ratio))
    if sigma2 <= 0 or not np.isfinite(sigma2):
        sigma2 = max(float(np.var(y)) * 1e-4, 1e-9)
    return sigma2


class KalmanCIR:
    """Same recursive structure as KalmanOU (state x = estimated mean
    level, predict/update via Kalman gain each bar), but Q (process
    noise) and R (observation noise) are recomputed EVERY BAR as
    sigma2 * current_level rather than fixed constants -- the direct
    consequence of CIR's diffusion term depending on the level. This
    makes the filter a time-varying-parameter linear Kalman filter (the
    transition itself is still linear in x, so no extended/unscented
    Kalman filter machinery is needed, just level-dependent Q/R)."""

    def __init__(self, phi: float, mu: float, sigma2: float, obs_noise_scale: float = 1.0,
                 q_mult: float = 1.0, mu_velocity: float = 0.0):
        self.phi = phi
        self.mu = mu
        self.sigma2 = sigma2
        self.mu_velocity = mu_velocity
        self.obs_noise_scale = max(obs_noise_scale, 0.01)
        self.q_mult = max(q_mult, 1e-6)
        self.x = mu
        self.P = self.sigma2 * max(mu, 1e-9) * self.obs_noise_scale

    def _q_at(self, level: float) -> float:
        return self.sigma2 * max(level, 1e-9) * max(1 - self.phi ** 2, 1e-6) * self.q_mult

    def predict(self):
        self.mu += self.mu_velocity
        q = self._q_at(self.x)
        self.x = self.phi * self.x + (1 - self.phi) * self.mu
        self.P = self.phi ** 2 * self.P + q

    def update(self, z: float):
        self.predict()
        r = self.sigma2 * max(z, 1e-9) * self.obs_noise_scale
        k = self.P / (self.P + r)
        self.x = self.x + k * (z - self.x)
        self.P = (1 - k) * self.P

    @property
    def theta(self) -> float:
        return -np.log(self.phi) if 0 < self.phi < 1 else 1e-6

    def sigma_stat(self, level: float | None = None) -> float:
        """Level-dependent stationary std: sqrt(sigma2 * level / (2*theta))
        -- the CIR stationary distribution is Gamma with variance
        sigma2*mu/(2*theta) at the LONG-RUN mean; using the current
        filtered level x instead of mu makes the band width track price
        the way CIR's variance actually does, rather than freezing it at
        one calibration's mu."""
        lvl = self.x if level is None else level
        return float(np.sqrt(self.sigma2 * max(lvl, 1e-9) / max(2 * self.theta, 1e-12)))

    @property
    def half_life_bars(self) -> float:
        """Same formula as OU (ln(2)/theta) -- the mean-reversion SPEED
        comes from the drift term, which is identical between OU and
        CIR; only the noise/band-width around that reversion differs."""
        return np.log(2) / max(self.theta, 1e-12)


def run_cir_mean_reversion(
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
    """CIR analogue of kalman_mean_reversion.run_mean_reversion() -- same
    entry/exit/risk-control shape (band-cross entry, mean-touch exit,
    z_stop/half_life_mult/tau_threshold/friction_hurdle/HMM gates), same
    output shape (bar_datetime, close, signal), so it plugs into the same
    sim_pnl()/run_cfg() trade-extraction helpers unmodified. Deliberately
    a leaner parameter set than the OU engine (no ATR-stop/ADX/Hurst/
    Wyckoff/trend_aware) -- this first pass tests whether the CIR
    diffusion assumption itself changes anything before porting every
    secondary risk control over.

    calib_window/recalib_every/k/z_stop/half_life_mult/tau_threshold/
    spread/friction_hurdle_mult/hmm_*: identical meaning to
    run_mean_reversion()'s parameters of the same name, just computed
    against CIR's level-dependent sigma_stat instead of OU's constant one.
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
            phi, mu, _sigma_ou = params  # OU's sigma unused here -- CIR estimates its own below
            sigma2 = estimate_cir_sigma(closes[t - calib_window:t], phi, mu)
            prev_x = kalman.x if kalman is not None else mu
            prev_p = kalman.P if kalman is not None else None
            kalman = KalmanCIR(phi, mu, sigma2, obs_noise_scale=obs_noise_scale, q_mult=q_mult)
            if prev_p is not None:
                kalman.x, kalman.P = prev_x, prev_p

        kalman.update(closes[t])
        out_mean[t] = kalman.x
        sigma_stat = kalman.sigma_stat()
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
