"""
Kalman Filter Mean Reversion (single-asset), ported from Quant Guild's
kts.py / ktsmr.ipynb (Ornstein-Uhlenbeck mean-level Kalman filter).

Core idea: treat price as an OU process dX = theta*(mu - X)*dt + sigma*dW.
Fit AR(1) on a rolling calibration window to get (phi, mu, sigma), then run
a 1D Kalman filter whose STATE is the estimated mean level itself (not the
price) -- each new bar blends the OU-predicted mean with the observed
price via the Kalman gain, so the "fair value" line adapts continuously
instead of staying frozen at one calibration window's sample mean (the
source notebook's whole point: a fixed sample mean silently "bleeds" P&L
when the window's estimate is biased, since there's no truly stationary
long-run mean for a real asset).

Base trading rule (straight from the source notebook): band = mean_level
+/- k * sigma_stat, sigma_stat = sigma / sqrt(2*theta). Enter short above
the upper band, long below the lower band, close when price returns to
mean_level. A smoke-test of exactly this against real XAUUSD M15 data
(2.4 trades/day at k=0.7) showed a decent win rate (~60%) but flat-to-
negative average P&L -- frequent small wins, occasional large loss, since
nothing bounds risk when price never actually reverts (the notebook's own
warning: no real asset has a truly stationary long-run mean). The 5 risk
controls below (all opt-in, all off by default = the notebook's exact
rule) were added specifically to address that failure mode, matching the
gaps: dynamic Z-score kill, half-life-based time stop, ATR-based absolute
stop, ADX/Hurst regime filters, and a process-noise (Q) multiplier so the
mean can track price faster when it's lagging.
"""

import numpy as np
import pandas as pd


def estimate_ar1(closes: np.ndarray):
    """Fit AR(1) on a window of closes. Returns (phi, mu, sigma) or None if
    too few points. phi is the discrete mean-reversion coefficient
    (x[t] = c + phi*x[t-1] + resid), clipped to (0.01, 0.99) so the OU
    step below never diverges or freezes. mu is anchored to the window's
    sample mean (not the regression intercept) -- same choice kts.py
    makes, so the Kalman filter's own predict/update loop is what lets the
    mean level move away from that anchor over time, not the calibration
    step."""
    y = np.asarray(closes, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 5:
        return None
    mu = float(np.mean(y))
    x_lag, x_curr = y[:-1], y[1:]
    X = np.column_stack([np.ones_like(x_lag), x_lag])
    beta = np.linalg.lstsq(X, x_curr, rcond=None)[0]
    phi = float(np.clip(beta[1], 0.01, 0.99))
    resid = x_curr - (beta[0] + phi * x_lag)
    sigma = float(np.sqrt(np.mean(resid ** 2)))
    if sigma <= 0 or not np.isfinite(sigma):
        sigma = max(float(np.std(y)) * 0.01, 1e-9)
    return phi, mu, sigma


def estimate_trend_velocity(closes: np.ndarray) -> float:
    """OLS slope of price vs bar index over the same window estimate_ar1
    calibrates on -- the per-bar drift fed to KalmanOU's mu_velocity (see
    its docstring). A plain linear-regression slope, not itself Kalman-
    filtered; refreshed at the same cadence as phi/mu/sigma."""
    y = np.asarray(closes, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 5:
        return 0.0
    x = np.arange(len(y), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


class KalmanOU:
    """State x = estimated OU mean level. Parameters (phi, mu, Q, R) fixed
    at construction (set by the caller's recalibration cadence); only
    (x, P) evolve per bar. q_mult scales the process noise Q up from its
    calibrated value -- >1 makes the mean level track incoming price
    faster (less lag, but noisier); 1.0 reproduces the source notebook
    exactly.

    mu_velocity (default 0.0 = the source notebook's exact static-anchor
    rule) is a minimal Local-Linear-Trend extension: instead of mu staying
    pinned to the calibration window's sample mean until the next
    recalibration, it advances by mu_velocity every bar, so the OU
    attractor itself can drift with the prevailing trend (a trend-
    dominant asset like an index no longer forces every deviation to be
    read as "must revert to a fixed level"). This is deliberately NOT a
    full 2-state (level, velocity) Kalman filter with its own process
    noise on velocity -- mu_velocity is a single per-recalibration OLS
    slope estimate (see estimate_trend_velocity), refreshed at the same
    cadence as phi/mu/sigma. sigma_stat/theta below are unaffected by
    mu_velocity: it only shifts where the attractor is, not the variance
    of price around it."""

    def __init__(self, phi: float, mu: float, sigma: float, obs_noise_scale: float = 1.0,
                 q_mult: float = 1.0, mu_velocity: float = 0.0):
        self.phi = phi
        self.mu = mu
        self.sigma = sigma
        self.mu_velocity = mu_velocity
        self.Q = (sigma ** 2) * max(1 - phi ** 2, 1e-6) * max(q_mult, 1e-6)
        self.R = (sigma ** 2) * max(obs_noise_scale, 0.01)
        self.x = mu
        self.P = self.R

    def predict(self):
        self.mu += self.mu_velocity
        self.x = self.phi * self.x + (1 - self.phi) * self.mu
        self.P = self.phi ** 2 * self.P + self.Q

    def update(self, z: float):
        self.predict()
        k = self.P / (self.P + self.R)
        self.x = self.x + k * (z - self.x)
        self.P = (1 - k) * self.P

    @property
    def theta(self) -> float:
        return -np.log(self.phi) if 0 < self.phi < 1 else 1e-6

    @property
    def sigma_stat(self) -> float:
        """Stationary std of the OU process: sigma / sqrt(2*theta), theta
        derived from the discrete phi (theta = -ln(phi), unit-bar dt)."""
        return self.sigma / np.sqrt(max(2 * self.theta, 1e-12))

    @property
    def half_life_bars(self) -> float:
        """Bars for the OU process to revert halfway back to mu -- the
        textbook definition ln(2)/theta, in units of the input series'
        own bar spacing (whatever timeframe the caller fed in)."""
        return np.log(2) / max(self.theta, 1e-12)


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's ATR. First `period` values are NaN (warm-up)."""
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.nanmax(np.vstack([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ]), axis=0)
    return pd.Series(tr).ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()


def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """Wilder's ADX, approximated with an exponential (alpha=1/period)
    smoother instead of Wilder's exact recursive seeding -- close enough
    for a regime gate, not represented as bar-exact against a reference
    platform's ADX."""
    prev_high = np.concatenate([[np.nan], high[:-1]])
    prev_low = np.concatenate([[np.nan], low[:-1]])
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = _atr(high, low, close, period)
    smooth_plus = pd.Series(plus_dm).ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()
    smooth_minus = pd.Series(minus_dm).ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * smooth_plus / atr
        minus_di = 100 * smooth_minus / atr
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    return pd.Series(dx).ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy()


def _rolling_hurst(close: np.ndarray, window: int) -> np.ndarray:
    """Single-scale rescaled-range (R/S) Hurst estimate per rolling
    window of price differences: H = log(R/S) / log(window). A real
    generalized Hurst estimate regresses R/S across MULTIPLE window
    lengths and takes the slope -- this is the cheap single-scale
    version, good enough as a rough trending-vs-reverting gate (H<0.5
    mean-reverting, H>0.5 trending) but not a rigorous estimator; treat
    it as a first pass, not a validated signal on its own."""
    n = len(close)
    out = np.full(n, np.nan)
    diffs = np.diff(close, prepend=close[0])
    for t in range(window, n):
        r = diffs[t - window + 1:t + 1]
        mean_r = r.mean()
        y = np.cumsum(r - mean_r)
        rng = y.max() - y.min()
        s = r.std()
        if s <= 0 or rng <= 0:
            continue
        out[t] = np.log(rng / s) / np.log(window)
    return out


class VolatilityRegimeHMM:
    """3-state (LOW/MED/HIGH) hidden Markov volatility-regime filter,
    ported from Quant Guild's regime-switching bot (2025 lecture 74,
    final_product.py MarkovRegime class) -- ADX and the single-scale Hurst
    estimate above both failed as regime gates in testing; this is a
    properly Bayesian alternative (transition-matrix prior + Gaussian
    emission likelihood, filtered forward bar by bar) worth trying instead
    of guessing another ad hoc threshold indicator.

    Per-bar volatility = (high-low)/close. calibrate() buckets a
    historical window into LOW/MED/HIGH by simple 33rd/67th percentile
    split, fits a Gaussian emission mean/std per bucket, and estimates the
    transition matrix from the empirical bucket sequence (Laplace-
    smoothed). update() then runs one step of Bayesian filtering
    (predict via the transition matrix, update via the Gaussian
    likelihood of the new observation, normalize) and returns the
    maximum-a-posteriori regime index (0=LOW, 1=MED, 2=HIGH)."""

    def __init__(self):
        self.n_states = 3
        self.state_probs = np.array([1 / 3, 1 / 3, 1 / 3])
        self.transition_matrix = np.array([
            [0.90, 0.08, 0.02],
            [0.10, 0.80, 0.10],
            [0.02, 0.08, 0.90],
        ])
        self.emission_means = np.array([0.0005, 0.002, 0.005])
        self.emission_stds = np.array([0.0003, 0.001, 0.003])

    def calibrate(self, vols: np.ndarray):
        vols = vols[np.isfinite(vols) & (vols > 0)]
        if len(vols) < 20:
            return
        p33, p67 = np.percentile(vols, 33), np.percentile(vols, 67)
        assignments = np.zeros(len(vols), dtype=int)
        assignments[vols >= p33] = 1
        assignments[vols >= p67] = 2
        for regime in range(self.n_states):
            regime_vols = vols[assignments == regime]
            if len(regime_vols) >= 3:
                self.emission_means[regime] = np.mean(regime_vols)
                self.emission_stds[regime] = max(np.std(regime_vols), 1e-6)
        order = np.argsort(self.emission_means)
        self.emission_means = self.emission_means[order]
        self.emission_stds = self.emission_stds[order]
        counts = np.zeros((self.n_states, self.n_states))
        for t in range(1, len(assignments)):
            counts[assignments[t - 1], assignments[t]] += 1
        for i in range(self.n_states):
            row_sum = counts[i].sum()
            if row_sum > 0:
                self.transition_matrix[i] = (counts[i] + 0.1) / (row_sum + 0.3)
        self.state_probs = np.array([1 / 3, 1 / 3, 1 / 3])

    def _emission_likelihood(self, vol: float) -> np.ndarray:
        coeff = 1 / (self.emission_stds * np.sqrt(2 * np.pi))
        exponent = -0.5 * ((vol - self.emission_means) / self.emission_stds) ** 2
        return coeff * np.exp(exponent)

    def update(self, vol: float) -> int:
        if vol <= 0 or not np.isfinite(vol):
            return int(np.argmax(self.state_probs))
        prior = self.transition_matrix.T @ self.state_probs
        posterior = prior * self._emission_likelihood(vol)
        total = posterior.sum()
        self.state_probs = posterior / total if total > 0 else prior
        return int(np.argmax(self.state_probs))


def run_mean_reversion(
    bar_datetime: pd.Series,
    close: pd.Series,
    high: pd.Series | None = None,
    low: pd.Series | None = None,
    open_: pd.Series | None = None,
    volume: pd.Series | None = None,
    side: str = "both",
    wyckoff_wick_ratio: float | None = None,
    wyckoff_volume_mult: float | None = None,
    wyckoff_volume_window: int = 20,
    calib_window: int = 60,
    recalib_every: int = 1,
    obs_noise_scale: float = 1.0,
    q_mult: float = 1.0,
    k: float = 1.0,
    z_stop: float | None = None,
    half_life_mult: float | None = None,
    atr_period: int = 14,
    atr_stop_mult: float | None = None,
    adx_period: int = 14,
    adx_threshold: float | None = None,
    hurst_window: int | None = None,
    hmm_calib_bars: int | None = None,
    hmm_block_states: tuple[int, ...] = (2,),
    tau_threshold: float | None = None,
    spread: float | None = None,
    friction_hurdle_mult: float = 2.5,
    trend_aware: bool = False,
) -> pd.DataFrame:
    """Bar-by-bar OU/Kalman mean-level estimate plus the band-cross trading
    rule, over a single already-sorted-ascending price series (any
    timeframe -- caller decides which raw table to feed in). All
    parameters below `k` are opt-in risk controls (None/default = off,
    reproducing the source notebook's rule exactly):

    z_stop: kill the position if |price - mean_level| / sigma_stat, RE-
    COMPUTED EVERY BAR against the current (moving) mean/sigma_stat,
    reaches this many stationary std -- a genuine breakout/trend move
    rather than normal OU noise, per the reasoning that a live process
    shouldn't reach 3+ stationary std under the OU assumption itself.

    half_life_mult: close the position if held longer than
    half_life_mult * kalman.half_life_bars (ln(2)/theta, bars in the
    input series' own timeframe) without reverting -- the OU model's own
    "should have reverted by now" horizon, not an arbitrary bar count.

    atr_stop_mult / atr_period: requires `high`/`low`. Kills the position
    if adverse excursion from entry exceeds atr_stop_mult * ATR(atr_period)
    -- an absolute volatility floor under the statistical stops, meant to
    catch news spikes / flash moves the OU model has no concept of.

    adx_threshold / adx_period: requires `high`/`low`. Blocks NEW entries
    (does not affect open positions) while ADX(adx_period) > adx_threshold
    -- avoids fading a confirmed trend.

    hurst_window: blocks NEW entries while the rolling Hurst estimate
    (see _rolling_hurst) is >= 0.5 (trending regime, mean-reversion
    assumption likely violated).

    hmm_calib_bars / hmm_block_states: requires `high`/`low`. Blocks NEW
    entries while VolatilityRegimeHMM's filtered regime is in
    hmm_block_states (default (2,) = HIGH only). Calibrated once on the
    first hmm_calib_bars bars of volatility ((high-low)/close), then
    filtered forward bar by bar (proper Bayesian updating, not
    recalibrated on a rolling window like the AR(1) step above -- the
    transition matrix and emission Gaussians are assumed stable, only the
    belief state moves).

    tau_threshold: blocks NEW entries unless the current
    kalman.half_life_bars <= tau_threshold -- only take a reversion trade
    when the OU model itself says reversion should be fast, not just
    "eventually." Same half_life_bars used by half_life_mult's exit-side
    stop, applied here on the entry side instead.

    spread / friction_hurdle_mult: blocks NEW entries unless
    |price - mean_level| >= friction_hurdle_mult * spread -- requires the
    dislocation to be worth several spreads before paying to trade it at
    all, independent of the k/sigma_stat band (a real answer to "is this
    move big enough to survive the cost," in price units rather than
    statistical units). `spread` is the estimated round-trip cost in the
    same price units as `close` (e.g. 0.12 for a 1.2-pip XAUUSD spread).
    No-op if `spread` is None.

    trend_aware: if True, mu (the OU attractor) advances every bar by the
    calibration window's own OLS price-vs-time slope (see
    estimate_trend_velocity / KalmanOU.mu_velocity), instead of staying
    pinned to a static sample mean between recalibrations. Intended for
    trend-dominant assets (see RESULTS.md's NDX100 discussion) where a
    static mean keeps reading "still trending up" as "deviated from mean,
    short it" -- off by default, reproducing the original static-anchor
    rule exactly.

    side: "both" (default, original symmetric rule), "long_only" (never
    opens a short -- for an asset with a persistent upward drift where
    fading rallies is structurally the wrong side), or "short_only".

    wyckoff_wick_ratio / wyckoff_volume_mult / wyckoff_volume_window:
    requires `open_`/`volume` in addition to `high`/`low`. An additional
    gate on NEW LONG entries only (never gates shorts), on top of the
    z<=-k band-cross condition, meant to require a Wyckoff-Spring-like
    rejection candle rather than any bar that merely closes outside the
    band:
      - wyckoff_wick_ratio: (min(open,close) - low) / (high - low) must be
        >= this fraction -- the bar's lower wick (rejection of the low)
        as a share of its full range. NOT the same formula as "(close -
        low) / (high - low)" (closing position within the bar) that also
        sometimes gets called a "wick ratio" -- that measures where the
        close landed, not how much of the bar was rejected wick; this
        module uses the wick-length version since it more directly
        matches "price dipped and was rejected."
      - wyckoff_volume_mult: current bar's volume must be >=
        wyckoff_volume_mult * the mean volume of the PRIOR
        wyckoff_volume_window bars (causal, excludes the current bar) --
        a volume-climax requirement.
      Either sub-condition is skipped (treated as passing) if its own
      parameter is None; both are no-ops if `open_`/`volume` aren't
      supplied.

    Returns one row per input bar (NaN columns before calib_window bars
    have accumulated) with mean_level, sigma_stat, band bounds, and a
    `signal` column: 'long'/'short' on entry, 'close_long'/'close_short'
    on a mean-touch exit, 'z_stop_long'/'z_stop_short',
    'time_stop_long'/'time_stop_short', 'atr_stop_long'/'atr_stop_short'
    on the corresponding risk-control exit.
    """
    if side not in ("both", "long_only", "short_only"):
        raise ValueError(f"side must be 'both'/'long_only'/'short_only', got {side!r}")

    n = len(close)
    closes = close.to_numpy(dtype=float)
    highs = high.to_numpy(dtype=float) if high is not None else None
    lows = low.to_numpy(dtype=float) if low is not None else None
    opens = open_.to_numpy(dtype=float) if open_ is not None else None
    vols = volume.to_numpy(dtype=float) if volume is not None else None

    atr = _atr(highs, lows, closes, atr_period) if (atr_stop_mult and highs is not None) else None
    adx = _adx(highs, lows, closes, adx_period) if (adx_threshold and highs is not None) else None
    hurst = _rolling_hurst(closes, hurst_window) if hurst_window else None

    lower_wick_ratio = None
    if wyckoff_wick_ratio is not None and opens is not None and highs is not None and lows is not None:
        rng = highs - lows
        with np.errstate(divide="ignore", invalid="ignore"):
            lower_wick_ratio = np.where(rng > 0, (np.minimum(opens, closes) - lows) / rng, np.nan)

    vol_sma = None
    if wyckoff_volume_mult is not None and vols is not None:
        vol_sma = pd.Series(vols).rolling(wyckoff_volume_window).mean().shift(1).to_numpy()

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
    position = 0  # 1 long, -1 short, 0 flat
    entry_price = None
    bars_held = 0

    for t in range(n):
        if t < calib_window:
            continue
        if kalman is None or (t - calib_window) % recalib_every == 0:
            params = estimate_ar1(closes[t - calib_window:t])
            if params is None:
                continue
            phi, mu, sigma = params
            mu_velocity = estimate_trend_velocity(closes[t - calib_window:t]) if trend_aware else 0.0
            prev_x = kalman.x if kalman is not None else mu
            prev_p = kalman.P if kalman is not None else None
            kalman = KalmanOU(phi, mu, sigma, obs_noise_scale=obs_noise_scale, q_mult=q_mult, mu_velocity=mu_velocity)
            if prev_p is not None:
                kalman.x, kalman.P = prev_x, prev_p  # carry filter state across recalibration

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
            if atr_stop_mult and atr is not None and np.isfinite(atr[t]):
                adverse = (entry_price - price) if position == 1 else (price - entry_price)
                if adverse >= atr_stop_mult * atr[t]:
                    signals[t] = "atr_stop_long" if position == 1 else "atr_stop_short"
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
                (adx_threshold and adx is not None and np.isfinite(adx[t]) and adx[t] > adx_threshold)
                or (hurst_window and hurst is not None and np.isfinite(hurst[t]) and hurst[t] >= 0.5)
                or (hmm_regime is not None and hmm_regime in hmm_block_states)
                or (tau_threshold is not None and kalman.half_life_bars > tau_threshold)
                or (spread is not None and abs(price - out_mean[t]) < friction_hurdle_mult * spread)
            )
            if regime_blocked:
                continue
            if side != "long_only" and price > out_upper[t]:
                position, entry_price, bars_held = -1, price, 0
                signals[t] = "short"
            elif side != "short_only" and price < out_lower[t]:
                wyckoff_ok = (
                    (wyckoff_wick_ratio is None or (
                        lower_wick_ratio is not None and np.isfinite(lower_wick_ratio[t])
                        and lower_wick_ratio[t] >= wyckoff_wick_ratio
                    ))
                    and (wyckoff_volume_mult is None or (
                        vol_sma is not None and np.isfinite(vol_sma[t]) and vol_sma[t] > 0
                        and vols[t] >= wyckoff_volume_mult * vol_sma[t]
                    ))
                )
                if wyckoff_ok:
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
