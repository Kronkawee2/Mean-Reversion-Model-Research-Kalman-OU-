"""
Jump-diffusion Ornstein-Uhlenbeck -- the fourth math-derived model, after
OU (constant variance), CIR (level-dependent variance), and GARCH-OU
(volatility-clustering variance) all failed to clear a validated edge.

    dX_t = theta*(mu - X_t)*dt + sigma*dW_t + J*dN_t

N_t is a Poisson jump process (intensity lambda); J is the jump size. This
adds a discrete "news shock" term on top of OU's continuous diffusion --
a standard extension used for commodities/interest rates/electricity
prices where large discrete moves (news, supply shocks) are common
alongside ordinary mean-reverting noise (Merton 1976's jump-diffusion;
Cartea & Figueroa 2005 apply the OU+jump combination specifically to
power prices). Not an invented rule.

The practically useful consequence: a jump-diffusion fit lets you tell
apart "ordinary mean-reverting noise" (small residuals, part of the
continuous diffusion) from "a jump" (a residual far outside the diffusion
part's own scale) INSTEAD of treating every large deviation as a
mean-reversion opportunity the way OU/CIR/GARCH-OU do. Two effects:
  1. sigma is estimated from the diffusion residuals ONLY (jumps
     excluded), so it isn't inflated by the rare large moves -- a
     tighter, more representative measure of "normal" noise than OU's
     plain residual std.
  2. Entries are BLOCKED when the current deviation itself looks like a
     jump (not ordinary mean-reverting noise) and open positions are
     stopped out immediately if a new jump occurs -- trading only the
     diffusion component, not fighting a structural break.
"""

import numpy as np
import pandas as pd

from analysis.strategies.kalman_mean_reversion import estimate_ar1, VolatilityRegimeHMM


def estimate_jump_diffusion(residuals: np.ndarray, jump_z: float = 3.5):
    """Splits AR(1) residuals into a diffusion part and a jump part by a
    simple threshold rule: any residual more than jump_z standard
    deviations (of the FULL residual sample) from zero is classified as a
    jump. Returns (sigma_diffusion, lambda_jump, jump_mask) where
    sigma_diffusion is the std of the non-jump residuals only and
    lambda_jump is the fraction of bars classified as jumps.

    Falls back to treating everything as diffusion (lambda_jump=0) if
    fewer than 20 residuals or if the jump filter would leave too few
    diffusion residuals to estimate sigma from.
    """
    eps = np.asarray(residuals, dtype=float)
    eps = eps[np.isfinite(eps)]
    n = len(eps)
    if n < 20:
        return float(np.std(eps)) if n > 1 else 1e-6, 0.0, np.zeros(n, dtype=bool)

    full_std = float(np.std(eps))
    if full_std <= 0:
        return 1e-6, 0.0, np.zeros(n, dtype=bool)

    jump_mask = np.abs(eps) > jump_z * full_std
    diffusion = eps[~jump_mask]
    if len(diffusion) < 10:
        return full_std, 0.0, np.zeros(n, dtype=bool)

    sigma_diffusion = float(np.std(diffusion))
    lambda_jump = float(np.mean(jump_mask))
    return sigma_diffusion, lambda_jump, jump_mask


class KalmanJumpOU:
    """Same recursive OU-drift structure as KalmanOU, but Q/R are built
    from sigma_diffusion (jump-excluded) instead of the plain residual
    std -- the mean estimate isn't dragged around by jump-sized moves."""

    def __init__(self, phi: float, mu: float, sigma_diffusion: float,
                 obs_noise_scale: float = 1.0, q_mult: float = 1.0):
        self.phi = phi
        self.mu = mu
        self.sigma = max(sigma_diffusion, 1e-8)
        self.obs_noise_scale = max(obs_noise_scale, 0.01)
        self.q_mult = max(q_mult, 1e-6)
        self.x = mu
        self.P = self.sigma ** 2 * self.obs_noise_scale

    def predict(self):
        x_pred = self.phi * self.x + (1 - self.phi) * self.mu
        q = self.sigma ** 2 * max(1 - self.phi ** 2, 1e-6) * self.q_mult
        self.P = self.phi ** 2 * self.P + q
        return x_pred

    def update(self, z: float):
        x_pred = self.predict()
        r = self.sigma ** 2 * self.obs_noise_scale
        k = self.P / (self.P + r)
        self.x = x_pred + k * (z - x_pred)
        self.P = (1 - k) * self.P

    @property
    def theta(self) -> float:
        return -np.log(self.phi) if 0 < self.phi < 1 else 1e-6

    @property
    def sigma_stat(self) -> float:
        return float(np.sqrt(self.sigma ** 2 / max(2 * self.theta, 1e-12)))

    @property
    def half_life_bars(self) -> float:
        return np.log(2) / max(self.theta, 1e-12)


def run_jump_ou_mean_reversion(
    bar_datetime: pd.Series,
    close: pd.Series,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    side: str = "both",
    calib_window: int = 60,
    recalib_every: int = 5,
    obs_noise_scale: float = 1.0,
    q_mult: float = 1.0,
    k: float = 1.8,
    z_stop: float | None = None,
    jump_z: float = 3.5,
    half_life_mult: float | None = None,
    hmm_calib_bars: int | None = None,
    hmm_block_states: tuple[int, ...] = (2,),
    tau_threshold: float | None = None,
    spread: float | None = None,
    friction_hurdle_mult: float = 2.5,
) -> pd.DataFrame:
    """Jump-diffusion analogue of run_mean_reversion(): same entry/exit
    shape (k*sigma_stat bands, z_stop, half-life time-stop, tau/friction
    entry filters, HMM regime block), but sigma_stat is built from
    sigma_diffusion (jumps excluded from the estimate) and two new jump-
    aware rules are added:
      - entry is BLOCKED if the CURRENT deviation itself is jump-sized
        (|price - mean| > jump_z * sigma_diffusion) -- a jump is a
        structural break, not a mean-reversion setup.
      - an open position is closed immediately ("jump_stop") if a NEW
        jump-sized move occurs while in the trade.
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
    out_sigma_diff = np.full(n, np.nan)
    out_upper = np.full(n, np.nan)
    out_lower = np.full(n, np.nan)
    out_lambda_jump = np.full(n, np.nan)
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
            sigma_diffusion, lambda_jump, _mask = estimate_jump_diffusion(resid, jump_z=jump_z)
            prev_x = kalman.x if kalman is not None else mu
            prev_p = kalman.P if kalman is not None else None
            kalman = KalmanJumpOU(phi, mu, sigma_diffusion, obs_noise_scale=obs_noise_scale, q_mult=q_mult)
            if prev_p is not None:
                kalman.x, kalman.P = prev_x, prev_p
            current_lambda = lambda_jump
        out_lambda_jump[t] = current_lambda

        kalman.update(closes[t])
        out_mean[t] = kalman.x
        sigma_stat = kalman.sigma_stat
        out_sigma_diff[t] = kalman.sigma
        out_upper[t] = kalman.x + k * sigma_stat
        out_lower[t] = kalman.x - k * sigma_stat

        price = closes[t]
        deviation = price - out_mean[t]
        is_jump_now = abs(deviation) > jump_z * kalman.sigma

        hmm_regime = None
        if hmm is not None and t >= hmm_calib_bars and np.isfinite(hmm_vols[t]):
            hmm_regime = hmm.update(hmm_vols[t])

        if position != 0:
            bars_held += 1
            if is_jump_now:
                signals[t] = "jump_stop_long" if position == 1 else "jump_stop_short"
                position, entry_price, bars_held = 0, None, 0
                continue
            z_now = deviation / sigma_stat if sigma_stat > 0 else 0.0
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
                is_jump_now
                or (hmm_regime is not None and hmm_regime in hmm_block_states)
                or (tau_threshold is not None and kalman.half_life_bars > tau_threshold)
                or (spread is not None and abs(deviation) < friction_hurdle_mult * spread)
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
        "sigma_diffusion": out_sigma_diff,
        "lambda_jump": out_lambda_jump,
        "upper_band": out_upper,
        "lower_band": out_lower,
        "signal": signals,
    })
