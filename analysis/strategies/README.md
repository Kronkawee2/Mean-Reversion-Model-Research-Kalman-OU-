# strategies/

Turns everything built in `analysis/smc_crt/`, `analysis/features/`, and
`analysis/divergence/` into a directional trade signal.

## HTF Bias Engine (`htf_bias_engine.py`) — Pass 1

For a given symbol/bar, aggregates SMC zone-state, CRT equilibrium,
indicator trend, volume profile, divergence, and liquidity sweeps into one
`bullish` / `bearish` / `neutral` bias plus a `confluence_score` on a
±100 scale (`bias` flips at ±50). Persisted to `curated_<symbol>.htf_bias`,
one row per h1 bar, via `run_htf_bias_detection.py`.

Component weights (see the module docstring for full reasoning): SMC
zone-imbalance is dominant (±30, capped), CRT equilibrium and indicator
trend are secondary confirmation (±15/±20), volume profile is a small
modifier (±10), liquidity sweeps read like CRT (±15, single most-recent-
event, not summed). Hidden divergence reinforces additively (capped ±24);
regular divergence dampens the whole score multiplicatively (floored at
0.7225, i.e. never crushes more than ~2 signals' worth).

### Session weighting: static vs dynamic

Both modes are fully supported, equally tested options — set via
`session_weighting_mode` on `HTFBiasEngine.compute_bias()`. Default is
`'static'` when the argument is omitted; that default is a convenience,
not an endorsement — pick whichever mode fits the use case.

- **`'static'`** (default): fixed UTC clock-hour sessions — Asian
  00:00–06:00 (×0.8), London 07:00–16:00 (×1.0), NY 12:00–21:00 (×1.0),
  killzone/London-NY overlap 12:00–16:00 (×1.2). Assumes the killzone is
  always the highest-liquidity window, which is usually but not always true.

- **`'dynamic'`**: 6h UTC buckets aligned to the h6 timeframe
  (00-06/06-12/12-18/18-24). Weight isn't tied to clock time at all — a
  bucket starts "quiet" (×1.0) and flips to "elevated" (×1.2) only once an
  actual liquidity sweep (BSL/SSL) is detected within it, from that bar
  onward (causal — never elevates a bar off a sweep that, from that bar's
  own point in time, hasn't happened yet), resetting at the next 6h
  boundary. Captures real activity outside the traditional killzone (e.g.
  an Asian-session news spike) that static would otherwise underweight
  purely because of the clock.

Both modes scale the exact same two components (`crt_contribution`,
`liquidity_sweep_contribution`) and leave SMC/indicator/volume-profile
untouched, so they're comparable on exactly one variable: which
multiplier applies at each bar.

**Known limitation (not a bug — a real, unresolved tradeoff):** static
uses *three* distinct multiplier tiers (0.8 asian / 1.0 london-ny / 1.2
killzone); dynamic only has *two* (1.0 quiet / 1.2 elevated). Setting
dynamic's quiet baseline to match static's daytime default (1.0, done
deliberately so the two modes are apples-to-apples during London/NY
hours) means dynamic no longer discounts truly quiet Asian-hours bars the
way static's ×0.8 does. A real-data comparison on 581 gold h1 bars found
this produces a handful of disagreements in Asian hours that are pure
baseline-scale artifacts, not sweep-driven — separate from the 2 bars
that were genuinely event-driven (a real sweep changed the label). Giving
dynamic a matching third tier (e.g. a lower floor specifically for
buckets with no sweep AND no adjacent activity) would close this gap but
hasn't been built — pick static if a clean 3-tier Asian/London/NY
distinction matters more than event-responsiveness; pick dynamic if
reacting to actual liquidity events regardless of clock time matters more.

`compare_session_weighting_modes.py` reproduces the side-by-side
comparison against real data (bar-by-bar disagreements, event-driven vs
baseline-artifact split) if this tradeoff needs re-evaluating later.

### Liquidity sweeps (`analysis/smc_crt/liquidity_state.py`)

BSL/SSL detection reuses `SMCStructureEngine.detect_swings()` and
`SMCLiquidityEngine.detect_liquidity_sweeps()` as-is; wrapped for
persistence as point-in-time event rows (no lifecycle — a sweep resolves
fully on the bar it occurs) in `curated_<symbol>.liquidity_sweeps` via
`run_liquidity_sweep_detection.py`.

## Not yet built

LTF trigger logic, entry/stop/target calculation, and risk management are
explicitly out of scope for everything in this directory so far — HTF
bias only defines direction and zones; nothing here decides when or where
to actually enter a trade.
