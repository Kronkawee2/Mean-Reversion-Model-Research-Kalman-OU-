"""
HTF Bias Engine (Phase 3a): aggregates everything currently persisted on
HTF timeframes into a single directional bias (bullish/bearish/neutral)
plus a confluence score, per h1 bar. This is Pass 1 of strategies/ —
LTF trigger logic, entry/stop/target calculation, and risk management are
explicitly out of scope here; this module only produces the HTF bias
signal itself.

Does not touch analysis/strategies/engine.py's MTFStrategyEngine —
that class's calc_htf_bias() is a much simpler, differently-scoped
mechanism (reads smc_trend_bias off a freshly-computed in-memory
DataFrame for a live exec-TF filter check, no persistence, no confluence
score, no CRT/volume-profile/divergence inputs). It solves a different
problem than what this pass asks for, so this is a new additive module
rather than a rehabilitation — same judgment call as the Phase 2h survey
of detect_intermarket_divergence.

Design decisions confirmed with the user before building:
  1. Weighting: SMC-dominant. SMC zone-state (net active bullish vs
     bearish zone imbalance) carries the largest weight (up to ±30) since
     it's the most direct "where are the real zones" signal, matching
     both the original plan's emphasis on HTF zones defining bias and
     the weighting style already established in this codebase's
     SMCScoringEngine/DivergenceSignalGenerator (structure signals
     weighted higher than filter-style boosts). CRT equilibrium and
     indicator trend are secondary confirmation (±15-20 each). Volume
     profile is a smaller modifier (±10).
  2. Primary HTF timeframe: h1. Checked before proposing (not assumed):
     h1 is the only HTF timeframe with full SMC zone-state + Volume
     Profile coverage in curated_gold/curated_eurusd right now — h4 only
     has CRT equilibrium + indicator features, d1 only has indicator
     features + intermarket divergence. h4's CRT equilibrium is merged
     onto the h1 timeline as secondary confirmation via the same causal
     merge_asof(direction="backward") pattern used everywhere else in
     this project.
  3. Bias threshold: ±50 on a ±100 scale — reused directly from this
     codebase's existing SMCScoringEngine and DivergenceSignalGenerator
     conventions (score >=50 -> BUY/bullish, <=-50 -> SELL/bearish, else
     HOLD/neutral), not a new number.

Divergence handling (the one component that isn't just "weighted small"):
per the user's own framing, Regular divergence = caution/reversal risk,
Hidden divergence = trend-continuation support. Rather than giving
Regular divergence its own directional vote (which would contradict
calling it "caution"), it multiplicatively DAMPENS the rest of the
composite score toward neutral (one CAUTION_DECAY factor per active
Regular signal in the lookback window) while Hidden divergence ADDS to
the score in its own signaled direction (reinforcing the prevailing
read). Only h1 technical divergence (RSI/OBV/Stochastic/CCI) feeds this
component this pass — d1 intermarket divergence (XAU vs DXY etc.) is
economically meaningful over weeks, not well-suited to an hourly lookback
window the same way, so it's deliberately excluded here rather than
silently mixed in; a future pass could add it with its own, longer
lookback.

Zone activity is evaluated causally as of each bar (no look-ahead): a
zone counts as active if created_at_bar <= bar and it hasn't been
invalidated yet as of that bar (invalidated_at_bar is NULL or in the
future relative to the bar) — using the zone's FINAL stored state would
leak information about invalidations that hadn't happened yet at that
point in history. Both 'active' and 'mitigated' states count (a
mitigated zone has been touched but not broken, still real structure);
only 'invalidated' zones are excluded.

Zone counting is ALSO bounded by SMC_ZONE_RECENCY_WINDOW_BARS (added after
a 2-year real-data audit): a zone stops counting after that many hours
from its own creation regardless of invalidation status. Zones never
expire on their own — only invalidation removes them — so over a long
enough sustained one-directional market, one side's uninvalidated zone
count grows without bound and permanently saturates SMC_CONTRIBUTION_CAP,
turning the "SMC-dominant" signal into a static directional flag instead
of a graded one (confirmed: 100% cap-saturated continuously from 2025-Q2
onward in real gold h1 data). This makes SMC consistent with every other
component here, which already uses a bounded window (divergence: 20 bars,
CRT: session/candle-scoped) — SMC was the only unbounded accumulator.

Liquidity sweep component (added after Pass 1's calibration audit):
weighted like CRT (+/-15, single-state read), not like SMC, because a
sweep is a single recent event derived from swing structure, not a
cumulative standing-structure count. Deliberately a single
most-recent-event-in-lookback-window read (reusing the same 20-bar
window as divergence) rather than a sum over multiple sweep events in
the window — summing was exactly the mechanism that caused the hidden-
divergence overweighting bug fixed this same pass, so the new component
is built with that lesson applied from the start rather than repeating it.

Session weighting (added after Pass 1): a bounded multiplier (killzone
x1.2 / london x1.0 / ny x1.0 / asian-or-off-hours x0.8) applied ONLY to
crt_contribution and liquidity_sweep_contribution before summing — the
two components that are inherently about intraday institutional
liquidity/activity. SMC/indicator/volume-profile are not session-scaled;
scaling the whole confluence_score would have silently rescaled every
component this pass just spent two rounds carefully capping. Even at the
x1.2 extreme, CRT and liquidity sweep only reach +/-18 each (from a
+/-15 base) — nowhere near SMC's +/-30 dominance, preserving the
calibrated hierarchy. Session boundaries follow standard FX convention
(UTC): Asian 00:00-06:00, London 07:00-16:00, NY 12:00-21:00, killzone =
their 12:00-16:00 overlap; hours outside all three (21:00-23:59 and the
06:00-07:00 gap) fall back to the 'asian' (quiet/off-hours) bucket. This
is `session_weighting_mode='static'`, the default.

Dynamic session weighting (comparison mode, added for a side-by-side
evaluation against static): `session_weighting_mode='dynamic'` replaces
the fixed clock-based label with 6-hour UTC buckets aligned to the
project's existing h6 timeframe (00-06/06-12/12-18/18-24), and instead of
weighting by WHICH bucket a bar falls in, weights by WHETHER a liquidity
sweep has actually occurred within that bucket so far. A bucket starts
'quiet' (x0.8, same base as static's off-hours) and flips to 'elevated'
(x1.2, same peak as static's killzone) on the bar where a sweep is
detected — and only from that bar onward, resetting at the next 6h
boundary. This is deliberately causal in the same way every other
component here is: a bar can never be elevated by a sweep that, from
its own point in time, hasn't happened yet (rejected the alternative of
retroactively elevating a whole bucket once any bar in it sweeps, since
that would leak future information into earlier bars' scores). Applies
the multiplier to the same two components as static (crt_contribution,
liquidity_sweep_contribution) so the two modes are comparable on exactly
one changed variable — which multiplier value applies at each bar, not
which components get scaled.
"""

import numpy as np
import pandas as pd

# Component weights
SMC_WEIGHT_PER_NET_ZONE = 5.0
SMC_CONTRIBUTION_CAP = 30.0
# Recency-bounded rolling window (h1 bars) for SMC zone counting -- a zone
# only counts if created within this many bars of the current bar, on top
# of (not instead of) the existing invalidation check. Zones never expire
# on their own (only invalidate when price revisits them), so without this
# bound, a sustained one-directional market lets one side's uninvalidated
# zone count grow forever -- confirmed via real 2-year gold data: net
# imbalance went from a validated, varying 5-week range (mean +8, ~76%
# cap-saturated) to 100% saturated at the +30 cap continuously from
# 2025-Q2 onward (mean +185, up to +407), turning SMC into a static
# "market has been bullish" flag rather than a graded confluence signal.
# 720 bars (~30 days) chosen from the real zone-invalidation-time
# distribution: 95.2% of zones that ever naturally invalidate do so within
# 720 hours, so this captures nearly all genuinely still-relevant structure
# without truncating it -- and closely matches the ~840h (5-week) window
# the SMC-dominant weighting and +-30 cap were originally validated
# against, so the recalibrated system should behave like the one already
# confirmed sensible, sustained indefinitely rather than by dataset-length
# accident. Every other component in this engine already uses a bounded
# window (divergence: 20 bars, CRT: session/candle-scoped) -- this makes
# SMC consistent with that pattern instead of the one unbounded accumulator.
SMC_ZONE_RECENCY_WINDOW_BARS = 720

CRT_EQUILIBRIUM_WEIGHT = 15.0  # discount -> +15, premium -> -15

INDICATOR_EMA_FULL_STACK_WEIGHT = 15.0
INDICATOR_EMA_PARTIAL_WEIGHT = 7.0
INDICATOR_RSI_TILT_WEIGHT = 5.0
INDICATOR_RSI_BULLISH_LEVEL = 55.0
INDICATOR_RSI_BEARISH_LEVEL = 45.0
INDICATOR_CONTRIBUTION_CAP = 20.0

VOLUME_PROFILE_WEIGHT = 10.0  # close above session POC -> +10, below -> -10

HIDDEN_DIVERGENCE_WEIGHT = 12.0  # per active hidden signal, additive, own direction
HIDDEN_DIVERGENCE_CONTRIBUTION_CAP = 24.0  # clip the summed total (see module docstring: unlike CRT/indicator/VP, this component sums multiple independent signals and can otherwise dwarf every other component's cap when 3+ hidden signals cluster in the lookback window)
REGULAR_DIVERGENCE_CAUTION_DECAY = 0.85  # multiplicative, per active regular signal
REGULAR_DIVERGENCE_CAUTION_FLOOR = REGULAR_DIVERGENCE_CAUTION_DECAY ** 2  # 0.7225 — mirrors the hidden-divergence cap's "2 signals' worth" ceiling: without a floor, 3+ clustered regular signals can crush an otherwise-decisive raw score to false neutral (found via real-data validation: 2026-07-29 01:00 had 9 regular signals, caution_factor=0.2316, crushing raw=-94 to confluence=-35.45)
DIVERGENCE_LOOKBACK_BARS = 20  # h1 bars (~20 hours) a divergence signal is considered "active near" the current bar

LIQUIDITY_SWEEP_WEIGHT = 15.0  # single most-recent-event read within the lookback window, own direction
LIQUIDITY_SWEEP_LOOKBACK_BARS = DIVERGENCE_LOOKBACK_BARS  # reuse the same 20-bar window for consistency

# Standard FX convention, UTC. Killzone = London/NY overlap (highest liquidity).
# Hours outside all three named ranges (21:00-23:59, 06:00-07:00 gap) fall
# back to 'asian' as the quiet/off-hours bucket.
ASIAN_HOURS = range(0, 6)
LONDON_HOURS = range(7, 16)
NY_HOURS = range(12, 21)
KILLZONE_HOURS = range(12, 16)
SESSION_MULTIPLIER = {"killzone": 1.2, "london": 1.0, "ny": 1.0, "asian": 0.8}

# Dynamic (comparison) mode: 6h UTC buckets aligned to the h6 timeframe,
# weighted by whether a sweep has occurred in the bucket so far (causal),
# not by clock-labeled session. 'quiet' baseline matches static's own
# non-killzone default (1.0, i.e. london/ny) rather than static's off-hours
# floor (0.8) -- using 0.8 as the no-event baseline was found to unfairly
# penalize quiet-but-otherwise-normal buckets relative to static's daytime
# default, producing disagreements that were baseline-scale artifacts, not
# real event-driven differences (found via real-data comparison). 'elevated'
# matches static's own killzone ceiling (1.2) so the two modes differ ONLY
# in which multiplier applies at each bar, not in the multiplier range itself.
BUCKET_HOURS = 6
DYNAMIC_SESSION_MULTIPLIER = {"quiet": 1.0, "elevated": 1.2}

BULLISH_ZONE_TYPES = {"order_block_bullish", "fvg_bullish", "swing_support"}
BEARISH_ZONE_TYPES = {"order_block_bearish", "fvg_bearish", "swing_resistance"}

BIAS_THRESHOLD = 50.0

HTF_BIAS_COLUMNS = [
    "symbol", "timeframe", "bar_datetime", "bias", "confluence_score", "raw_score_before_caution",
    "smc_contribution", "smc_active_bullish_zones", "smc_active_bearish_zones",
    "crt_contribution", "crt_equilibrium_bias",
    "indicator_contribution",
    "volume_profile_contribution",
    "hidden_divergence_contribution", "hidden_divergence_count",
    "regular_divergence_caution_factor", "regular_divergence_count",
    "liquidity_sweep_contribution", "liquidity_sweep_direction",
    "session", "session_multiplier",
]


def classify_session(hour: int) -> str:
    if hour in KILLZONE_HOURS:
        return "killzone"
    if hour in LONDON_HOURS:
        return "london"
    if hour in NY_HOURS:
        return "ny"
    return "asian"


class HTFBiasEngine:
    """Aggregates SMC zone-state, CRT equilibrium, indicator trend, volume profile, and divergence into a single HTF bias per h1 bar."""

    def _smc_zone_counts(self, h1_bars: pd.DataFrame, smc_zones: pd.DataFrame) -> pd.DataFrame:
        """
        For each h1 bar, count zones active as of that bar (causal), split
        bullish vs bearish, via a sweep-line over creation/invalidation
        events rather than an O(bars * zones) nested loop.
        """
        n = len(h1_bars)
        bull_active = np.zeros(n, dtype=int)
        bear_active = np.zeros(n, dtype=int)
        if smc_zones.empty:
            return pd.DataFrame({"smc_active_bullish_zones": bull_active, "smc_active_bearish_zones": bear_active})

        bar_times = h1_bars["price_datetime"].values
        for _, zone in smc_zones.iterrows():
            # No `state` filter here deliberately: `state` is the zone's
            # FINAL/terminal state from the full historical scan (most
            # zones that are ever invalidated end up with state=
            # 'invalidated'), not a per-bar time-varying value. Filtering
            # on it would wrongly exclude a zone's entire active/mitigated
            # history just because it was later invalidated — the causal
            # created_at_bar/invalidated_at_bar window below already
            # correctly bounds exactly when the zone counts, including
            # correctly excluding it after its own invalidation. (Caught
            # by test_zone_causality_no_lookahead: an eventually-
            # invalidated zone was undercounted to zero for its entire
            # active lifetime before this fix.)
            direction = 1 if zone["zone_type"] in BULLISH_ZONE_TYPES else (-1 if zone["zone_type"] in BEARISH_ZONE_TYPES else 0)
            if direction == 0:
                continue
            created = np.datetime64(zone["created_at_bar"])
            invalidated = zone["invalidated_at_bar"]
            invalidated = np.datetime64(invalidated) if pd.notnull(invalidated) else None
            # Recency bound: a zone stops counting after
            # SMC_ZONE_RECENCY_WINDOW_BARS hours from its own creation,
            # regardless of invalidation status -- on top of, not instead
            # of, the invalidation check below. See SMC_ZONE_RECENCY_WINDOW_BARS
            # for why (unbounded counting saturates the cap permanently in
            # a sustained trend).
            recency_cutoff = created + np.timedelta64(SMC_ZONE_RECENCY_WINDOW_BARS, "h")

            active_mask = (bar_times >= created) & (bar_times < recency_cutoff)
            if invalidated is not None:
                active_mask &= bar_times < invalidated
            if direction == 1:
                bull_active += active_mask
            else:
                bear_active += active_mask

        return pd.DataFrame({"smc_active_bullish_zones": bull_active, "smc_active_bearish_zones": bear_active})

    def _indicator_contribution(self, row) -> float:
        ema20, ema50, ema200 = row.get("ema_20"), row.get("ema_50"), row.get("ema_200")
        rsi = row.get("rsi_14")
        score = 0.0

        if pd.notnull(ema20) and pd.notnull(ema50) and pd.notnull(ema200):
            if ema20 > ema50 > ema200:
                score += INDICATOR_EMA_FULL_STACK_WEIGHT
            elif ema20 < ema50 < ema200:
                score -= INDICATOR_EMA_FULL_STACK_WEIGHT
            elif ema20 > ema50:
                score += INDICATOR_EMA_PARTIAL_WEIGHT
            elif ema20 < ema50:
                score -= INDICATOR_EMA_PARTIAL_WEIGHT

        if pd.notnull(rsi):
            if rsi > INDICATOR_RSI_BULLISH_LEVEL:
                score += INDICATOR_RSI_TILT_WEIGHT
            elif rsi < INDICATOR_RSI_BEARISH_LEVEL:
                score -= INDICATOR_RSI_TILT_WEIGHT

        return float(np.clip(score, -INDICATOR_CONTRIBUTION_CAP, INDICATOR_CONTRIBUTION_CAP))

    def compute_bias(
        self,
        h1_bars: pd.DataFrame,
        smc_zones: pd.DataFrame,
        crt_equilibrium: pd.DataFrame,
        features_h1: pd.DataFrame,
        volume_profile: pd.DataFrame,
        divergence_h1: pd.DataFrame,
        liquidity_sweeps: pd.DataFrame,
        symbol: str,
        timeframe: str = "h1",
        session_weighting_mode: str = "static",
    ) -> pd.DataFrame:
        """
        h1_bars: price_datetime, close_price (raw_gold/raw_eurusd.h1), sorted ascending.
        smc_zones: symbol/timeframe/zone_type/state/created_at_bar/invalidated_at_bar (curated.smc_signals, timeframe='h1').
        crt_equilibrium: bar_datetime, zone_bias (curated.crt_signals, signal_type='equilibrium', timeframe='h4').
        features_h1: bar_datetime, ema_20, ema_50, ema_200, rsi_14 (curated.features, timeframe='h1').
        volume_profile: session_date, session_poc (curated.volume_profile, timeframe='h1', one row per bin — caller should pass distinct per-session rows).
        divergence_h1: bar_datetime, divergence_class, direction (curated.divergence_signals, timeframe='h1', technical types only).
        liquidity_sweeps: bar_datetime, direction (curated.liquidity_sweeps, timeframe='h1').
        session_weighting_mode: 'static' (default, fixed clock-based session labels) or
            'dynamic' (6h buckets, weight follows whether a sweep has occurred in-bucket so far).
        Returns one row per h1 bar (HTF_BIAS_COLUMNS).
        """
        if session_weighting_mode not in ("static", "dynamic"):
            raise ValueError(f"session_weighting_mode must be 'static' or 'dynamic', got {session_weighting_mode!r}")
        if h1_bars.empty:
            return pd.DataFrame(columns=HTF_BIAS_COLUMNS)

        base = h1_bars.reset_index(drop=True).copy()
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])
        base["close_price"] = base["close_price"].astype(float)
        n = len(base)

        # --- SMC zone-state contribution ---
        zone_counts = self._smc_zone_counts(base, smc_zones)
        net_imbalance = zone_counts["smc_active_bullish_zones"] - zone_counts["smc_active_bearish_zones"]
        smc_contribution = np.clip(net_imbalance * SMC_WEIGHT_PER_NET_ZONE, -SMC_CONTRIBUTION_CAP, SMC_CONTRIBUTION_CAP)

        # --- CRT equilibrium contribution (h4, backward-filled onto h1) ---
        if not crt_equilibrium.empty:
            crt_sorted = crt_equilibrium.sort_values("bar_datetime").copy()
            crt_sorted["bar_datetime"] = pd.to_datetime(crt_sorted["bar_datetime"])
            merged_crt = pd.merge_asof(
                base[["price_datetime"]], crt_sorted[["bar_datetime", "zone_bias"]],
                left_on="price_datetime", right_on="bar_datetime", direction="backward",
            )
            crt_bias = merged_crt["zone_bias"]
        else:
            crt_bias = pd.Series([None] * n)
        crt_contribution = np.where(crt_bias == "discount", CRT_EQUILIBRIUM_WEIGHT,
                                     np.where(crt_bias == "premium", -CRT_EQUILIBRIUM_WEIGHT, 0.0))

        # --- Indicator trend contribution (h1 features) ---
        if not features_h1.empty:
            feat_sorted = features_h1.sort_values("bar_datetime").copy()
            feat_sorted["bar_datetime"] = pd.to_datetime(feat_sorted["bar_datetime"])
            merged_feat = pd.merge_asof(
                base[["price_datetime"]], feat_sorted[["bar_datetime", "ema_20", "ema_50", "ema_200", "rsi_14"]],
                left_on="price_datetime", right_on="bar_datetime", direction="backward",
            )
            indicator_contribution = merged_feat.apply(self._indicator_contribution, axis=1).values
        else:
            indicator_contribution = np.zeros(n)

        # --- Volume profile contribution (h1, per-session POC) ---
        if not volume_profile.empty:
            vp_sorted = volume_profile.drop_duplicates(subset=["session_date"]).sort_values("session_date").copy()
            vp_sorted["session_start"] = pd.to_datetime(vp_sorted["session_date"])
            # session_date is a DATE column (pymysql -> datetime.date -> pandas
            # infers datetime64[s]) while price_datetime is DATETIME (datetime.datetime
            # -> datetime64[us]) -- merge_asof refuses to join mismatched units.
            base_keys = base[["price_datetime"]].copy()
            base_keys["price_datetime"] = base_keys["price_datetime"].astype("datetime64[us]")
            vp_sorted["session_start"] = vp_sorted["session_start"].astype("datetime64[us]")
            merged_vp = pd.merge_asof(
                base_keys, vp_sorted[["session_start", "session_poc"]],
                left_on="price_datetime", right_on="session_start", direction="backward",
            )
            poc = merged_vp["session_poc"].astype(float)
            vp_contribution = np.where(
                poc.isna(), 0.0,
                np.where(base["close_price"].values > poc.values, VOLUME_PROFILE_WEIGHT, -VOLUME_PROFILE_WEIGHT),
            )
        else:
            vp_contribution = np.zeros(n)

        # --- Divergence: hidden reinforces (additive), regular dampens (multiplicative caution) ---
        hidden_contribution = np.zeros(n)
        hidden_count = np.zeros(n, dtype=int)
        regular_count = np.zeros(n, dtype=int)
        if not divergence_h1.empty:
            div_sorted = divergence_h1.sort_values("bar_datetime").reset_index(drop=True).copy()
            div_sorted["bar_datetime"] = pd.to_datetime(div_sorted["bar_datetime"])
            div_times = div_sorted["bar_datetime"].values
            div_class = div_sorted["divergence_class"].values
            div_dir = div_sorted["direction"].values

            for i in range(n):
                t = base["price_datetime"].iloc[i]
                window_start = t - pd.Timedelta(hours=DIVERGENCE_LOOKBACK_BARS)
                in_window = (div_times > np.datetime64(window_start)) & (div_times <= np.datetime64(t))
                if not in_window.any():
                    continue
                classes = div_class[in_window]
                dirs = div_dir[in_window]

                hidden_mask = classes == "hidden"
                hidden_count[i] = hidden_mask.sum()
                if hidden_mask.any():
                    hidden_contribution[i] = sum(
                        HIDDEN_DIVERGENCE_WEIGHT if d == "bullish" else -HIDDEN_DIVERGENCE_WEIGHT
                        for d in dirs[hidden_mask]
                    )
                regular_count[i] = (classes == "regular").sum()

        # Cap the summed total (not per-signal): 3+ hidden signals clustering
        # in the same lookback window would otherwise let this component
        # exceed every other component's cap, including SMC's supposedly-
        # dominant ±30 — found via real-data validation (2026-07-22/23 gold
        # pullback scored "bullish" off 7 stacked hidden signals = +84 while
        # price fell 2%). Capped at ±24 (2 signals' worth) per user decision.
        hidden_contribution = np.clip(hidden_contribution, -HIDDEN_DIVERGENCE_CONTRIBUTION_CAP, HIDDEN_DIVERGENCE_CONTRIBUTION_CAP)

        caution_factor = np.maximum(REGULAR_DIVERGENCE_CAUTION_DECAY ** regular_count, REGULAR_DIVERGENCE_CAUTION_FLOOR)

        # --- Liquidity sweep contribution: single most-recent-event read ---
        sweep_contribution = np.zeros(n)
        sweep_direction = np.array([None] * n, dtype=object)
        if not liquidity_sweeps.empty:
            sweep_sorted = liquidity_sweeps.sort_values("bar_datetime").reset_index(drop=True).copy()
            sweep_sorted["bar_datetime"] = pd.to_datetime(sweep_sorted["bar_datetime"])
            sweep_times = sweep_sorted["bar_datetime"].values
            sweep_dir = sweep_sorted["direction"].values

            for i in range(n):
                t = base["price_datetime"].iloc[i]
                window_start = t - pd.Timedelta(hours=LIQUIDITY_SWEEP_LOOKBACK_BARS)
                in_window = (sweep_times > np.datetime64(window_start)) & (sweep_times <= np.datetime64(t))
                if not in_window.any():
                    continue
                # Most recent event in the window only — not a sum (see
                # module docstring: summing is exactly the mechanism that
                # caused hidden divergence's overweighting bug).
                last_idx = np.where(in_window)[0][-1]
                d = sweep_dir[last_idx]
                sweep_direction[i] = d
                sweep_contribution[i] = LIQUIDITY_SWEEP_WEIGHT if d == "bullish" else -LIQUIDITY_SWEEP_WEIGHT

        # --- Session classification + bounded multiplier (CRT + sweep only) ---
        if session_weighting_mode == "static":
            hours = base["price_datetime"].dt.hour.values
            session = np.array([classify_session(int(h)) for h in hours], dtype=object)
            session_mult = np.array([SESSION_MULTIPLIER[s] for s in session])
        else:
            sweep_dt_set = set(pd.to_datetime(liquidity_sweeps["bar_datetime"])) if not liquidity_sweeps.empty else set()
            session = np.empty(n, dtype=object)
            session_mult = np.empty(n)
            current_bucket = None
            elevated = False
            for i in range(n):
                t = base["price_datetime"].iloc[i]
                bucket_start = (t.hour // BUCKET_HOURS) * BUCKET_HOURS
                bucket_key = (t.normalize(), bucket_start)
                if bucket_key != current_bucket:
                    current_bucket = bucket_key
                    elevated = False
                if t in sweep_dt_set:
                    elevated = True
                state = "elevated" if elevated else "quiet"
                session[i] = f"{bucket_start:02d}-{(bucket_start + BUCKET_HOURS) % 24:02d}_{state}"
                session_mult[i] = DYNAMIC_SESSION_MULTIPLIER[state]

        raw_score_before_caution = (
            smc_contribution.values
            + (crt_contribution * session_mult)
            + indicator_contribution
            + vp_contribution
            + hidden_contribution
            + (sweep_contribution * session_mult)
        )
        confluence_score = np.clip(raw_score_before_caution * caution_factor, -100.0, 100.0)

        bias = np.where(confluence_score >= BIAS_THRESHOLD, "bullish",
                         np.where(confluence_score <= -BIAS_THRESHOLD, "bearish", "neutral"))

        out = pd.DataFrame({
            "symbol": symbol, "timeframe": timeframe, "bar_datetime": base["price_datetime"],
            "bias": bias,
            "confluence_score": np.round(confluence_score, 2),
            "raw_score_before_caution": np.round(raw_score_before_caution, 2),
            "smc_contribution": np.round(smc_contribution.values, 2),
            "smc_active_bullish_zones": zone_counts["smc_active_bullish_zones"].values,
            "smc_active_bearish_zones": zone_counts["smc_active_bearish_zones"].values,
            "crt_contribution": np.round(crt_contribution, 2),
            "crt_equilibrium_bias": crt_bias.values,
            "indicator_contribution": np.round(indicator_contribution, 2),
            "volume_profile_contribution": np.round(vp_contribution, 2),
            "hidden_divergence_contribution": np.round(hidden_contribution, 2),
            "hidden_divergence_count": hidden_count,
            "regular_divergence_caution_factor": np.round(caution_factor, 4),
            "regular_divergence_count": regular_count,
            "liquidity_sweep_contribution": np.round(sweep_contribution, 2),
            "liquidity_sweep_direction": sweep_direction,
            "session": session,
            "session_multiplier": session_mult,
        })
        return out[HTF_BIAS_COLUMNS]
