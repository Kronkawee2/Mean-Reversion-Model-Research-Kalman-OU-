# Decision Log

## Project Origin & Goals

This project is a systematic trading pipeline for XAUUSD (and EURUSD), built around Smart Money Concepts / ICT structure (order blocks, FVGs, swing highs/lows, liquidity sweeps), Candle Range Theory (Asian session range/sweep, range equilibrium), a technical and inter-market divergence matrix, and volume profile — all rolled up into a confluence-scored higher-timeframe bias, with lower-timeframe entry triggers planned on top of that bias.

The point of this project isn't to produce a chart-drawing tool. The user's goal is to develop genuine, disciplined quant trading skill, and the project is meant to be held to a real quant research bar before any signal it produces gets trusted with real money — specifically the standard set early on by Bailey & López de Prado's work on the Deflated Sharpe Ratio, minimum sample size requirements before a backtest result means anything, and walk-forward validation rather than a single in-sample fit. Every phase in this log should be read against that bar, not against "does it run."

The raw data layer pulls from two different sources for a reason. The pipeline originally ran entirely on Yahoo Finance OHLCV. MT5 (via an Eightcap live account) was added specifically for m5/m15/h1 because it reflects actual broker execution price and gives real-time intraday granularity Yahoo Finance can't provide at that resolution — Yahoo remains the source for h4/d1 and the macro instruments (DXY, US10Y, VIX, GDX). This is why the raw layer isn't a single unified feed: each source is used where it's actually the better source, not out of convenience.

Storage follows a Medallion-style layering: `raw_*` databases hold immutable ingested OHLCV exactly as fetched, `curated_*` databases hold derived signals computed from that raw data (zone state, CRT, indicators, divergence, volume profile, HTF bias), and a `mart` layer is intended for whatever final trade-ready output sits on top. The point of keeping these separate is that each layer can be independently validated and re-run without corrupting the others — a bug found in curated logic can be fixed and the whole curated layer regenerated from raw without ever touching or re-fetching raw data, and a raw data bug (like the timezone issues found and fixed mid-project) can be corrected and the curated layer rebuilt on top of it.

A few of the user's explicit priorities have shaped design decisions throughout, beyond just "make it work": liquidity and session awareness mattered enough to justify building both liquidity sweep detection and two different session-weighting approaches (static clock-based and dynamic sweep-driven) specifically so they could be compared against each other with real data rather than one being assumed correct. Wanting to eventually understand and tune this logic personally, not just receive a black box, is why this decision log exists at all. And preferring a system usable in an on-demand, incremental-sync workflow rather than something requiring 24/7 uptime is why `mt5_sync_service.py` supports both a single-shot `--once` mode and a long-running `--interval` loop mode — it's meant to fit around the user's own schedule, not force one.

As of this log's start, the data pipeline (MT5 + Yahoo ingestion, with the timezone-correctness issues found and fixed), SMC zone-state, CRT, the full technical + inter-market divergence matrix, volume profile, and the HTF Bias Engine (including liquidity sweeps and session weighting) are built and validated against real data. LTF trigger logic, risk management, a backtester, and any kind of dashboard/execution layer are explicitly not yet built. This is a work in progress — treat anything not listed above as not existing yet, not as an oversight.

---

## Divergence framework: pivot-side ambiguity bug

**What was decided:** `classify_divergence()` requires an explicit `pivot_type` argument (`'low'` or `'high'`) rather than inferring divergence class from price/indicator direction alone.

**Why:** the four-number pattern (price direction, indicator direction) is genuinely ambiguous without knowing which side of price action the pivot pair sits on. "Price up, indicator down" means `HIDDEN_BULLISH` on a low-pivot pair but `REGULAR_BEARISH` on a high-pivot pair — there is no way to tell those apart from the two price values and two indicator values alone. This was caught by the first pass's own tests (RSI Regular-only implementation), not found by inspection.

**Evidence:** `classify_divergence()`'s docstring in `technical_divergence_state.py` spells out both branches explicitly (`pivot_type='low'` → REGULAR_BULLISH/HIDDEN_BULLISH; `pivot_type='high'` → REGULAR_BEARISH/HIDDEN_BEARISH) specifically to prevent this ambiguity from being reintroduced.

**Where it lives in code:** `analysis/divergence/technical_divergence_state.py::classify_divergence()`, called with `pivot_type="low"` for the low-pivot loop and `pivot_type="high"` for the high-pivot loop in `TechnicalDivergenceEngine.detect()`.

**Status:** fixed, and the fix generalized cleanly — OBV, Stochastic, and CCI were later added to the divergence matrix with zero framework changes, confirming the indicator-agnostic design (adding an indicator is a call-site change, not new detection logic) actually holds.

---

## CRT signal-family split: Asian sweep (h1) vs Range Equilibrium (h4/h6/d1)

**What was decided:** `CRTStateEngine` treats Asian range/sweep and Range Equilibrium as two separate signal families with different timeframe requirements and different state models, rather than one unified CRT concept — Asian range/sweep always reads h1 regardless of what timeframe the caller asks for; Equilibrium reads whatever timeframe (h4/h6/d1) is requested.

**Why:** Asian session boundaries are UTC-clock-defined (00:00–06:00), and h4/h6/d1 candles straddle those boundaries — computing the Asian high/low from anything coarser than h1 would misrepresent the true session high/low and miss smaller sweeps entirely. Equilibrium, by contrast, is a per-candle midpoint concept that's meant to live on the higher timeframe as originally planned. The two also don't share a state model: a sweep is a single-bar wick-and-close event with a real pending→swept/expired lifecycle (the level is watched across a bounded session window), while equilibrium is a stateless per-candle snapshot recomputed fresh every candle — there's no "state" column populated for equilibrium rows at all.

**Evidence:** `analysis/smc_crt/crt_state.py` module docstring documents both the timeframe-split rationale and the deliberate non-parallel state models side by side.

**Where it lives in code:** `analysis/smc_crt/crt_state.py::CRTStateEngine.detect_asian_sweeps()` (h1, pending/swept/expired) and `::calc_equilibrium()` (h4/h6/d1, stateless). `run_crt_detection.py` calls both from a single `--timeframe` invocation.

**Status:** stable, unchanged since Phase 2b.

---

## EURUSD flat-price bug: per-instrument decimal precision + reject_flat_ohlc guard

**What was decided:** `YahooFinanceClient.fetch_gold_data()`'s `decimals` parameter must be passed explicitly per instrument (5 for EUR/USD, 2 for gold) rather than relying on a shared default, and a separate `reject_flat_ohlc` flag drops any row where open==high==low==close after rounding — but only when explicitly enabled, since it's only safe for high-precision instruments.

**Why:** the fetcher originally hardcoded 2 decimal places for every symbol. Gold genuinely only needs 2, but EUR/USD needs 5 — rounding EUR/USD to 2 decimals collapsed every quote to cent-level values (e.g. 1.15000-style dead-flat rows), producing flat OHLC across 100% of `raw_eurusd.h4/d1` history at the time this was caught. The `reject_flat_ohlc` guard exists specifically so this class of bug can't silently reappear and get treated as real data, but it can't just be turned on unconditionally: gold at its correct 2-decimal precision *legitimately* produces flat quiet-day bars (~12% of its real d1 history) — enabling the guard for gold would wrongly discard real, quiet trading days as if they were the same rounding bug.

**Evidence:** documented directly in `fetch_gold_data()`'s docstring, including the exact figures (100% of eurusd h4/d1 flat before the fix, ~12% of gold d1 legitimately flat).

**Where it lives in code:** `fetcher/yahoo_finance_client.py::YahooFinanceClient.fetch_gold_data(decimals, reject_flat_ohlc)`. Called with `decimals=5, reject_flat_ohlc=True` for EUR/USD and `decimals=2, reject_flat_ohlc=False` for gold in `scripts/sync/quant_backend.py::GOLD_EURUSD_ASSETS`.

**Status:** fixed; the per-instrument decimals requirement and the guard's gold-vs-FX asymmetry are both enforced by convention (docstring + correct call-site args), not by a runtime check that would reject a wrong call.

---

## Two divergence models remain deferred: EUR yield-spread and MTF Alignment Divergence

**What was decided:** the divergence matrix was closed at 11/12 models, not 12/12 — EUR vs yield-spread and MTF Alignment Divergence are both explicitly deferred as backlog items, not abandoned and not silently skipped.

**Why:** the two have entirely different blockers, not a shared one.

EUR vs yield-spread is deferred indefinitely because no EU/German government yield data source currently exists anywhere in the pipeline — every other inter-market model (XAU vs DXY/US10Y/GDX/SPDR, COT gold/EUR) had a real, already-integrated data source to build against; this one doesn't.

MTF Alignment Divergence's blocker is different and, unlike the yield-spread case, was only discovered by actually doing the work: the design was fully worked out (HTF = h1 only, matching how h1 is already the primary/authoritative HTF elsewhere in this project — `crt_engine`, `htf_bias_engine`; indicator-matched alignment — HTF RSI Hidden only aligns with LTF RSI Regular, not cross-indicator, for interpretability; `TechnicalDivergenceEngine` reused as-is for both the HTF and LTF sides, no new detection primitive needed) and the LTF prerequisites were built (m5/m15 added to the features pipeline — `run_feature_engineering.py`; `--timeframe` flag added to `run_divergence_detection.py`; m5/m15 `pivot_window` values derived from real data by matching h1's implied ~3-hour pivot window in real time — 12 bars at m15, 36 bars at m5 — rather than blind-copying h1's `pivot_window=3`, which was confirmed to over-produce pivots by ~4-15x at LTF resolution).

Before building the actual confluence-persistence pipeline, an empirical pre-check was run (same discipline as every timeframe-specific constant in this project — validate against real data before implementing, not after): for each HTF Hidden Divergence event, does a matching-direction LTF Regular Divergence event land within a candidate window, at a rate that clears what pure random chance (same event counts, uniformly randomized timestamps) would produce anyway? Tested across 5 indicator×symbol combinations (RSI/OBV/Stochastic/CCI on gold, RSI on EURUSD) and 10 candidate windows (5h-720h). **Every combination came back negative or negligible** — real match rates sat at or below the random-null baseline from 5h out to ~320h, only reaching near-zero lift at the trivially wide 480-720h (20-30 day) range, which isn't a meaningful confluence window in any tradeable sense. No combination showed the kind of real-vs-random separation that would justify building the pipeline.

**This is a real, informative negative finding, not a stalled task** — the design and the empirical prerequisite work are both complete; what's deferred is the persistence pipeline itself, because the data doesn't currently support it. EUR yield-spread is blocked by missing data; MTF Alignment is blocked by an empirical result.

**Evidence:** `analysis/divergence/technical_divergence_state.py`'s "Explicitly deferred" section has the full negative-finding writeup (which combinations were tested, the window range, the result) for MTF Alignment; `analysis/divergence/intermarket_divergence_state.py` documents the EUR yield-spread blocker. The empirical pre-check itself is a real, reusable script — `scripts/diagnostic/test_mtf_alignment_divergence_lift.py` — not just a one-off session transcript, so it can be re-run later against more history, a different symbol, or a different methodology without re-deriving it from scratch.

**Where it lives in code:** EUR yield-spread has no corresponding detection code (never started). MTF Alignment has real supporting code — the LTF features/divergence-detection prerequisites (`run_feature_engineering.py`, `run_divergence_detection.py`) are genuinely built and usable for other purposes — but no confluence/alignment detection or persistence table, since that's exactly the part the empirical result didn't support building.

**Status:** deferred, not scheduled — EUR yield-spread has a clear path forward if a EU/German yield source appears; MTF Alignment's path forward is re-running (or redesigning) the empirical pre-check if more history accumulates or a different indicator/methodology looks promising, not a known blocker being worked through.

---

## HTF Bias Engine: initial weighting design (SMC-dominant, h1 primary, ±50 threshold)

**What was decided:** three foundational design choices, each confirmed with the user before writing code rather than defaulted silently: (1) SMC zone-state imbalance is the dominant weighted component (up to ±30), with CRT equilibrium and indicator trend as secondary confirmation (±15–20) and volume profile as a smaller modifier (±10); (2) h1 is the primary/authoritative HTF timeframe, with h4 CRT equilibrium merged on as secondary confirmation; (3) the bias threshold is ±50 on a ±100 confluence-score scale.

**Why:** SMC zone-state was judged the most direct "where are the real zones" signal, matching both the original plan's emphasis on HTF zones defining bias and this codebase's existing convention (structure signals weighted higher than filter-style boosts). h1 was picked because, at the time, it was the only HTF timeframe with full SMC zone-state + Volume Profile coverage in the curated databases — h4 only had CRT equilibrium + indicator features, d1 only had indicator features + intermarket divergence. The ±50 threshold reused the same convention already established by `SMCScoringEngine`/`DivergenceSignalGenerator` elsewhere in the project, rather than inventing a new number.

**Evidence:** design questions and the user's confirmed answers are recorded in `analysis/strategies/htf_bias_engine.py`'s module docstring under "Design decisions confirmed with the user before building."

**Where it lives in code:** `analysis/strategies/htf_bias_engine.py` — `SMC_WEIGHT_PER_NET_ZONE`, `SMC_CONTRIBUTION_CAP`, `CRT_EQUILIBRIUM_WEIGHT`, `INDICATOR_CONTRIBUTION_CAP`, `VOLUME_PROFILE_WEIGHT`, `BIAS_THRESHOLD`.

**Status:** SMC's cap and dominance concept still stand, but see the "SMC recency-window fix" entry below — the counting mechanism underneath this weight was later found to break down at longer history lengths and was corrected.

---

## HTF Bias Engine: divergence handling (hidden = reinforcement, regular = caution, not a competing vote)

**What was decided:** Hidden divergence (continuation signal, per the user's own framing) adds to the confluence score in its own signaled direction. Regular divergence (reversal-risk signal) does NOT cast its own directional vote — instead it multiplicatively dampens the entire score toward neutral, one decay factor per active regular signal in the lookback window.

**Why:** giving Regular divergence its own directional vote would contradict calling it "caution" — a caution signal shouldn't compete with the rest of the confluence stack for direction, it should discount confidence in whatever direction the rest of the stack already points.

**Where it lives in code:** `analysis/strategies/htf_bias_engine.py::compute_bias()` — hidden divergence loop adds `HIDDEN_DIVERGENCE_WEIGHT` per signal in its own direction; `caution_factor = REGULAR_DIVERGENCE_CAUTION_DECAY ** regular_count` multiplies the whole pre-caution score.

**Status:** mechanism unchanged; both its cap (hidden) and floor (regular) were added later — see next two entries.

---

## Hidden divergence contribution cap (±24)

**What was decided:** `hidden_divergence_contribution` is capped at ±24 (the summed total across all active hidden signals in the 20-bar lookback, not per-signal).

**Why:** the component was originally uncapped and additive per-signal (+12 each), and since up to 4 independent detectors (RSI/OBV/Stochastic/CCI) can all fire within the same 20-bar window, real-data validation surfaced a case where 7 stacked hidden signals produced +84 — dwarfing SMC's supposedly-dominant ±30 cap. Concretely: the 2026-07-22→23 gold window scored "bullish" (confluence score often pinned at +100) while price actually fell ~2% (4131.83 → 4049.66) over that same window, entirely because of hidden-divergence stacking. ±24 (2 signals' worth) was chosen specifically so hidden divergence could reinforce but never single-handedly override SMC's ±30 dominance.

**Evidence:** the ±84 real-data reading and the 2026-07-22/23 price/score mismatch were found by querying the full per-bar component breakdown after Pass 1's real-data validation, not by reasoning about the code in the abstract.

**Where it lives in code:** `analysis/strategies/htf_bias_engine.py::HIDDEN_DIVERGENCE_CONTRIBUTION_CAP = 24.0`, applied via `np.clip()` on the summed total inside `compute_bias()`.

**Status:** fixed and regression-verified — `MAX(ABS(hidden_divergence_contribution))` across the full validated dataset is exactly 24.00, never higher.

---

## Regular divergence caution floor (0.7225)

**What was decided:** `caution_factor = max(0.85 ** regular_count, 0.7225)` — the multiplicative dampening from regular divergence can never crush a score below floor, no matter how many regular signals cluster in the lookback window.

**Why:** mirror-image of the hidden divergence bug, found by proactively auditing the caution mechanism after fixing hidden divergence. `regular_divergence_count` reached 9 in real data (same 4 detectors, same clustering risk), and `0.85^9 = 0.2316` was able to crush a genuinely strong structural read (raw score -94, well past the ±50 threshold on its own) down to a false neutral (-35.45 → -21 range). The floor value itself was derived the same way the hidden-divergence cap was: `0.85^2 = 0.7225`, i.e. "roughly 2 signals' worth" — deliberately reusing the same signal-count assumption as the hidden-divergence fix rather than introducing a different one, so the two fixes stay reasoning-consistent with each other.

**Evidence:** the 2026-07-29 01:00 bar (`regular_divergence_count=6`, `raw_score_before_caution=-94.00`) went from `confluence_score=-35.45` (neutral, before the fix) to `-67.91` (correctly bearish, after) — the concrete before/after cited when the fix was validated.

**Where it lives in code:** `analysis/strategies/htf_bias_engine.py::REGULAR_DIVERGENCE_CAUTION_FLOOR`.

**Status:** fixed and regression-verified — `MIN(regular_divergence_caution_factor)` across the full dataset is exactly 0.7225, never lower.

---

## Proactive audit of CRT / indicator / volume-profile / liquidity-sweep for the same overweighting risk

**What was decided:** after finding the hidden-divergence and regular-divergence bugs, every other component was checked for the same "capped on paper, unbounded in practice" failure mode — CRT equilibrium, indicator trend, and volume profile were confirmed structurally immune (each is a single bounded state read per bar, not a sum of independent events, so per-bar magnitude can never exceed its documented cap regardless of how many consecutive bars share the same reading). No code changes were made to these three.

**Why:** the hidden-divergence bug's root cause was specifically "summing multiple independent signal events without a cap on the running total" — a mechanism CRT/indicator/VP simply don't have (each reads exactly one current state value, no accumulation across a lookback window). This was verified empirically (real-data distinct-value queries), not just argued from code review.

**Evidence:** `crt_contribution` and `volume_profile_contribution` were confirmed to take only their two extreme values (`{-15, 15}` and `{-10, 10}`) across the entire real dataset, never anything summed or intermediate. `indicator_contribution`'s 12 distinct real-data values were confirmed to exactly match the combinatorial set of `ema_component + rsi_component`, with no value outside that set — ruling out any unbounded-compounding path. A separate consecutive-run-length check (how many bars in a row share an identical value) confirmed the apparent "persistence" of these components reflects their genuinely slower-updating source data (one h4 candle, one session day), not an accumulation bug — persistence affects how long a bias *label* stays stable, not how large any single bar's *score* can get.

**Status:** closed, no fix needed — this was a verification pass, not a bug fix.

---

## Liquidity sweep detection: point-in-time event, new table, single most-recent-event read

**What was decided:** three sub-decisions, each confirmed with the user before building: (1) liquidity sweeps are persisted as point-in-time event rows with no active/mitigated/invalidated lifecycle (unlike SMC zones) and no pending/swept/expired lifecycle either (unlike CRT's Asian levels) — a sweep is fully resolved the instant its wick-through-and-close-back-in bar closes; (2) a new `liquidity_sweeps` table was created rather than overloading `smc_signals` or `crt_signals`, since neither table's shape fits a level+single-event; (3) when integrated into the HTF Bias Engine, a sweep contributes via a single most-recent-event-in-window read (±15, matching CRT's weight), not a sum over multiple events in the lookback window.

**Why:** decision (1) and (2) follow from the same reasoning as the CRT signal-family split above — the state model should match what the signal actually is, not be copied from a nearby table for convenience. Decision (3) was made deliberately in anticipation of the hidden-divergence bug rather than after — since summing multiple independent events without a cap was *already known*, at that point, to be the exact failure mode that broke hidden divergence, the new component was built with a single-read mechanism from day one instead of needing the same fix applied twice.

**Where it lives in code:** `analysis/smc_crt/liquidity_state.py::LiquiditySweepStateEngine` (detection/persistence), `storage/schema_curated.sql::liquidity_sweeps` (table), `analysis/strategies/htf_bias_engine.py::LIQUIDITY_SWEEP_WEIGHT`/`LIQUIDITY_SWEEP_LOOKBACK_BARS` (integration).

**Status:** built, unit-tested (including a causality/no-look-ahead check and a most-recent-event-not-summed check), and validated against real gold data (75 sweeps in the original 5-week window; 1,420 after the later timezone-driven re-sync expanded history to ~2 years).

---

## Session weighting: static (clock-based) mode

**What was decided:** a bounded multiplier — killzone (London/NY overlap, 12:00–16:00 UTC) ×1.2, London/NY (non-overlap) ×1.0, Asian/off-hours ×0.8 — applied only to `crt_contribution` and `liquidity_sweep_contribution`, not to the whole confluence score and not to SMC/indicator/volume-profile.

**Why:** scaling the entire score would have silently rescaled every component this project had just spent two rounds carefully capping (the hidden-divergence and regular-divergence fixes above). Scoping the multiplier to only the two components that are inherently about intraday institutional activity keeps the "cap the influence, don't let one factor dominate silently" principle intact — even at the ×1.2 extreme, CRT and liquidity sweep only reach ±18 from a ±15 base, nowhere near SMC's ±30 dominance.

**Where it lives in code:** `analysis/strategies/htf_bias_engine.py::SESSION_MULTIPLIER`, `classify_session()`.

**Status:** stable; kept alongside dynamic mode as an equally-supported option (see next entry), not superseded by it.

---

## Session weighting: dynamic (sweep-driven) mode, and the comparison methodology

**What was decided:** a second, parallel session-weighting mode — `session_weighting_mode='dynamic'` — using 6-hour UTC buckets (aligned to the h6 timeframe) instead of fixed clock sessions, where a bucket starts "quiet" and flips to "elevated" only from the bar a real liquidity sweep occurs onward (never retroactively, to preserve causality), resetting at the next 6h boundary. Both modes are first-class, equally tested, equally documented — `session_weighting_mode` defaults to `'static'` only as a convenience, not because dynamic is considered experimental.

**Why:** the user's hypothesis was that fixed clock-based session weighting assumes the killzone is always the highest-liquidity window, which isn't always true — a real Asian-session news spike could get systematically underweighted purely because of the clock. Rather than accept or reject that hypothesis by argument, both mechanisms were built and compared against the same real 581-bar gold window. The comparison surfaced a real methodology bug along the way: dynamic's first version used a 0.8 "quiet" floor copied from static's Asian discount, which unfairly penalized dynamic during normal London/NY hours relative to static's own 1.0 baseline there — corrected to `quiet=1.0` (matching static's own non-killzone default) so the two modes differ on exactly one variable (which multiplier applies at each bar), not on differing baselines.

**Evidence:** after the baseline-mismatch fix, only 2 of 581 bars (0.34%) showed a genuinely event-driven disagreement between the two modes (a real sweep changing the bias label) — including one clean example (2026-08-04 23:00) where static's Asian-clock discount let a real bearish sweep get overridden by SMC dominance into a bullish label, while dynamic correctly kept it neutral, matching the bearish price action that actually followed. A separate, still-open limitation was also found and documented rather than fixed: static uses three multiplier tiers (Asian/London-NY/killzone) but dynamic only has two (quiet/elevated), so dynamic can't fully replicate static's Asian-hours discount — this shows up as a handful of Asian-hours disagreements that are baseline-tier artifacts, not real event-driven differences.

**Where it lives in code:** `analysis/strategies/htf_bias_engine.py::DYNAMIC_SESSION_MULTIPLIER`, `BUCKET_HOURS`; `scripts/diagnostic/compare_session_weighting_modes.py` reproduces the comparison against real data if the tradeoff needs re-evaluating. Documented in `analysis/strategies/README.md`.

**Status:** both modes closed and shipped; the 3-tier-vs-2-tier limitation is documented as a known, deliberate tradeoff, not resolved.

---

## Timezone data-integrity workstream — Pass A: fetcher fixes

**What was decided:** three distinct bugs were found and fixed in the raw-data fetchers, discovered while investigating an unrelated m5 sync gap.

1. **MT5 incremental-fetch truncation direction.** `get_rates_incremental()` kept the newest `count` bars (`.tail(count)`) when a gap exceeded `count`, silently and permanently dropping the older portion. Fixed to keep the oldest bars (`.head(count)`) so a looping sync service pages forward through a large gap instead of jumping to "now" and abandoning the middle. Found via a real ~88.5h outage: M5 needed ~1,062 bars (>500, truncated, ~562 oldest bars permanently lost) while M15/H1 stayed under 500 bars and were unaffected — explaining why only M5 showed a permanent gap.
2. **MT5 local-timezone query misdirection.** `mt5.copy_rates_range()` silently reinterprets a naive datetime using the *local system timezone*, not UTC — a documented MetaTrader5 Python API quirk. The old `_to_naive_utc()` converted to UTC wall-clock numbers and stripped tzinfo, which then got re-interpreted as local time by MT5, shifting every range query by the local UTC offset (confirmed as exactly 7h on the machine this was found on). Fixed by converting to *local* wall-clock time before stripping tzinfo, so MT5's own reinterpretation lands back on the intended UTC instant.
3. **MT5 broker-clock offset.** The broker's raw epoch data (both ticks and rates) runs ahead of true UTC by a DST-dependent amount (measured +3.00h, consistent with EEST) — not documented anywhere in the MT5 API, not a fixed constant. Fixed with dynamic calibration: `check_symbol()` measures the offset fresh via a live tick every call, and `get_rates`/`get_latest_rates`/`get_ticks` all correct for it — including shifting the *query* bounds by the same offset before the local-timezone compensation from fix #2, since `copy_rates_range` indexes by broker clock, not true UTC.
4. **Yahoo fetchers (3 files: `yahoo_finance_client.py`, `market_fetcher.py`, `sync_step1.py`).** yfinance returns a tz-aware, exchange-local `DatetimeIndex` (`America/New_York` for GC=F/DX-Y.NYB/GDX, `Europe/London` for EURUSD=X, `America/Chicago` for ^TNX/^VIX) — all three fetchers stripped tzinfo without converting to UTC first, silently writing exchange-local wall-clock time into the DB labeled as UTC. Fixed with one shared helper (`fetcher/timezone_utils.py::to_utc_naive()`) used by all three call sites, so the fix can't drift out of sync between files and is automatically correct for every exchange/DST state via each timestamp's own tzinfo.

**Why:** discovered while investigating why M5 specifically had a permanent historical gap that M15/H1 didn't — the investigation kept surfacing one more layer (truncation direction → local-tz query bug → broker-clock offset → the same class of bug independently on the Yahoo side) rather than stopping at the first fix found.

**Evidence:** every fix was verified with a concrete before/after/true-UTC-reference triplet, not just "verified live" — e.g. MT5's fixed code landed a query for "the last hour ending now" within 5 minutes of true system UTC, versus the old code's 7h05m miss; Yahoo's GC=F fix matched its own `.tz_convert("UTC")` ground truth exactly (0 diff) versus the old code's 4h miss.

**Where it lives in code:** `scripts/sync/mt5_data_fetcher.py::_to_naive_utc()`, `MT5DataFetcher._calibrate_broker_utc_offset()`, `_correct_to_true_utc()`, `get_rates_incremental()`; `fetcher/timezone_utils.py::to_utc_naive()`. Tests: `tests/test_mt5_data_fetcher_incremental.py`, `tests/test_mt5_data_fetcher_timezone.py`, `tests/test_mt5_broker_offset.py`, `tests/test_yahoo_timezone_utils.py`.

**Status:** fixed, tested, and confirmed live against the real MT5 terminal and real yfinance calls. No stored data touched in this pass by design — see Pass B.

---

## Timezone data-integrity workstream — Pass B: raw intraday re-sync

**What was decided:** full delete-and-refetch of every raw intraday table using the Pass A-corrected fetchers: gold/eurusd h1/m5/m15 (MT5) and gold/eurusd h4 + DXY h1 (Yahoo). d1 tables were *not* blanket re-fetched — instead spot-checked against live yfinance ground truth, and only re-fetched where real evidence of a problem was found.

**Why:** re-fetching everything blindly, including tables that were already correct, would waste time and risk introducing new problems into data that didn't need touching — the standard set was "evidence first, then act," matching how every other fix in this project was validated.

**Evidence:** the d1 spot-check found 5 of 6 tables clean (gold/DXY/US10Y/VIX/GDX — all US-exchange tickers, whose negative UTC offset means local midnight always falls within the same UTC calendar day) and one real, quantified bug in `raw_eurusd.d1` — `Europe/London`'s positive offset (BST, +1h in summer) means local midnight falls on the *previous* UTC day, confirmed with a concrete example (a Friday close was mislabeled to Friday's date; it's actually Thursday 23:00 UTC) and a full-history count: 152 of 260 trading days in the prior year were mislabeled by exactly one day (BST months only — GMT winter months were already correct since the offset is 0 then). Intraday tables jumped from ~5 weeks of history to ~2 years once the truncation-direction bug (Pass A, fix #1) stopped discarding it — gold h1 alone went from 604 to 11,320 rows, all duplicate-checked (`COUNT(*) == COUNT(DISTINCT price_datetime)`) to confirm the jump was genuine depth, not duplication.

**Where it lives in code:** `scripts/diagnostic/resync_intraday_pass_b.py` (MT5 + Yahoo intraday re-sync, with an in-memory sanity gate before any DELETE). d1 re-fetch for eurusd only, done ad hoc via `YahooFinanceClient` directly.

**Status:** complete for all tables identified as needing it; the 5 clean d1 tables were deliberately left untouched.

---

## Timezone data-integrity workstream — Pass C: curated layer full recompute

**What was decided:** every curated table was regenerated from the Pass B-corrected raw data, in dependency order: smc_signals → crt_signals → features → volume_profile → divergence_signals → liquidity_sweeps → htf_bias (liquidity_sweeps and htf_bias were swapped from the originally-planned order once it was noticed `scripts/detection/run_htf_bias_detection.py` reads `liquidity_sweeps` as an input — running htf_bias first would have computed against stale sweep data). EURUSD was recomputed too, not just gold, since Pass B's fetcher fix incidentally populated EURUSD's MT5 tables for the first time (they'd never been synced before — unrelated to the timezone bug itself, but a real scope change worth calling out explicitly).

**Why:** curated tables are derived from raw timestamps; once those timestamps changed, every downstream table computed from them was stale by construction, not just "possibly affected."

**Evidence, and two real bugs caught along the way (not timezone bugs — exposed by finally having enough history to trigger them):**
1. **Stale-duplicate upsert risk.** Every `run_*.py` detection script is upsert-only (`INSERT ... ON DUPLICATE KEY UPDATE`) — re-running detection against differently-timestamped raw data left old rows as orphaned duplicates rather than overwriting them (caught on `smc_signals`: a run that inserted 4,856 new rows left the table at 5,129, i.e. 273 stale leftovers). Fixed procedurally, not by changing the scripts: an explicit `DELETE` for the relevant symbol/timeframe before every regeneration step, for the rest of Pass C.
2. **`divergence_signals` DECIMAL overflow.** `prev_pivot_indicator`/`curr_pivot_indicator` were `DECIMAL(10,4)` (max ~999,999) — fine for 5 weeks of history, but 2 years of cumulative OBV reaches 2,904,568, well past that limit. Widened to `DECIMAL(24,4)` (matching `features.obv`'s existing precision) via `ALTER TABLE` on both databases plus `schema_curated.sql`.

**Where it lives in code:** `storage/schema_curated.sql` (`divergence_signals.prev_pivot_indicator`/`curr_pivot_indicator`). No detection logic changed in this pass — only data was regenerated and one schema column widened.

**Status:** complete; all 7 tables regenerated for both symbols, with a previously-hand-verified example (2026-07-10 Asian range high/low) confirmed to have genuinely changed under the corrected timestamps, as expected, and flagged rather than silently left stale.

---

## SMC zone-counting: unbounded accumulator → 720-bar recency window

**What was decided:** SMC zone counting for the HTF Bias Engine's net-imbalance calculation was changed from unbounded ("any zone ever created and not yet invalidated") to a recency-bounded rolling window — a zone only counts if created within the last `SMC_ZONE_RECENCY_WINDOW_BARS = 720` h1 bars (~30 days), on top of (not instead of) the existing invalidation check.

**Why:** zones never expire on their own by design — only invalidation removes them. Once Pass C expanded gold's history from 5 weeks to 2 years, this became a real problem rather than a theoretical one: gold's 2-year bull run meant bearish (resistance) zones kept invalidating fast as price broke through them, while bullish (support) zones almost never got revisited and piled up uninvalidated. The net-imbalance metric — meant to represent *current* structure — was actually measuring "cumulative uninvalidated zones since the dataset began." Quarterly saturation of the ±30 cap went from 76.2% (2024-Q3, still within the window's own warm-up period) to a permanent 100% from 2025-Q2 onward, with the mean climbing from +8 to as high as +355 — SMC had become a static "market has been bullish" flag for over a year of history, undermining the entire "SMC-dominant, graded confluence" premise for that period. This was architecturally inconsistent with every other component in the engine, all of which already use a bounded window (divergence: 20 bars, CRT: session/candle-scoped) — SMC was the only unbounded accumulator.

720 bars was chosen from two independent pieces of real data, not picked arbitrarily: (1) 95.2% of zones that ever naturally invalidate do so within 720 hours, so the window captures nearly all genuinely still-relevant structure without truncating it; (2) 720h closely matches the ~840h duration of the original 5-week window the SMC-dominant design and ±30 cap were validated against in the first place.

**Evidence:** post-fix, mean net-imbalance dropped from +185 to +14.7 (close to the original validated window's +8) and the sign now genuinely flips across quarters (2026-Q2 mean = -14.0) instead of climbing monotonically forever. A direct window-size sweep (200h/350h/500h/720h/1000h, each excluding its own warm-up period) confirmed steady-state cap-saturation *plateaus* at ~85–87% from 500h upward (500h: 86.8%, 720h: 85.8%, 1000h: 85.9% — flat, not climbing), and quarterly saturation with the fix applied oscillates 71.9–90.8% with no directional drift — the most recent quarter is the *lowest* reading in the series, not the highest. This confirmed the remaining ~85% steady-state saturation rate is real gold h1 market structure at this window size, not evidence the window is still too wide; the original 76.2% baseline was a warm-up-phase artifact (the entire original validation period had fewer than 720 hours of elapsed time to accumulate zones in), not a fair steady-state comparison.

**Where it lives in code:** `analysis/strategies/htf_bias_engine.py::SMC_ZONE_RECENCY_WINDOW_BARS`, applied inside `_smc_zone_counts()`. Test: `tests/test_htf_bias_engine.py::test_zone_recency_window_expires_uninvalidated_zones`.

**Status:** fixed, tested (exact-boundary unit test plus full quantitative real-data re-validation), and regression-checked — hidden divergence cap, regular divergence floor, and every other component's bounds were confirmed unaffected by this change.

---

## Repository layout: flat root → scripts/detection/diagnostic, tests/, docs/

**What was decided:** pure file reorganization, no logic changes — root-level scripts sorted into `scripts/sync/` (raw-data ingestion), `scripts/detection/` (all `run_*.py` curated-layer detection scripts), and `scripts/diagnostic/` (reusable investigative tools, with an `archive/` subfolder for historical one-offs); all `test_*.py` consolidated into `tests/`; `README-MT5.md` and `DECISIONS.md` moved into `docs/` (README.md stays at root as the front door).

**Why:** the root directory had accumulated ~30 loose Python files (sync scripts, 8 detection scripts, 3 diagnostic scripts, 16 test files) as the project grew phase by phase — readability, not any functional problem.

Diagnostic scripts were classified individually rather than moved uniformly: `resync_intraday_pass_b.py` and `compare_session_weighting_modes.py` were kept as genuinely reusable tools (a future full data re-sync, or a future re-evaluation of the session-weighting tradeoff, would reach for these again) and documented as such; `backfill_m5_gap.py` was archived — it fixed one specific, dated historical gap whose root cause is now permanently fixed, so the exact scenario it handles won't recur, and it's kept only as a record of the incident.

**Evidence:** every import/`sys.path` reference affected by the move was grepped for and fixed (not relied on from memory), including cross-package imports that didn't exist before the move (e.g. `scripts/diagnostic/compare_session_weighting_modes.py` importing from `scripts/detection/run_htf_bias_detection.py`). `docker-compose.yml` and the `Dockerfile` were updated to `COPY`/mount `scripts/` into the Airflow containers — which incidentally fixed a pre-existing, unrelated bug found while doing this: `quant_backend.py` was never copied into the Airflow image at all, so `airflow/dags/quant_daily_sync.py`'s `from quant_backend import QuantBackend` would have failed inside the container regardless of this reorg. All 16 tests pass from their new location, plus a live end-to-end run of `scripts/detection/run_htf_bias_detection.py` reproduced the exact same row counts and bias distribution as before the move.

**Where it lives in code:** `scripts/__init__.py`, `scripts/sync/__init__.py`, `scripts/detection/__init__.py`, `scripts/diagnostic/__init__.py`, `tests/__init__.py` (package markers enabling the qualified imports, e.g. `from scripts.sync.mt5_data_fetcher import MT5DataFetcher`).

**Status:** complete.

---

## Pre-push cleanup: .gitignore gap, dead sync_step1.py, stray empty directories

**What was decided:** three small fixes made in a pre-first-push audit, none logic changes: (1) `.gitignore` was missing `.env.mt5` — the file holding the live Eightcap MT5 credentials — so it would have been picked up by a blanket `git add`; widened the pattern to `.env.*` with explicit negations for the `.example` templates so this class of gap can't recur for any future `.env.*` file. (2) `scripts/sync/sync_step1.py` was deleted outright rather than neutralized — it connected to a hardcoded, wrong DB port (3306, not the live 3308) with a hardcoded password, was never imported by anything else in the codebase, and its entire functional scope (Yahoo sync for gold/eurusd/DXY/VIX/GDX/US10Y) was already fully covered by `quant_backend.py` (h4/d1) + MT5 ingestion (m5/m15/h1) + `market_fetcher.py` (macro d1/h1) — keeping a fully-redundant, non-functional script around as "reference" added no value. (3) Three empty, oddly-named directories under `storage/` (`schema_curated.sql;C`, `schema_mart.sql;C`, `schema_raw.sql;C` — apparent artifacts of an earlier shell command mishap) were confirmed untracked, unreferenced anywhere in the codebase, and genuinely empty before deletion.

**Why:** found during a dedicated pre-push `.gitignore`/credential audit — the standing rule throughout this project has been "verify empirically before deleting/trusting," applied here too: nothing was removed without first grepping for references and checking git tracking status.

**Evidence:** `git status --ignored` / `git add --dry-run` before-and-after confirmed `.env.mt5` changed from addable to correctly blocked; `git log --all -- .env` / `.env.mt5` confirmed neither was ever committed, so nothing had leaked to the remote. `git log --all -p -- "*.env*"` confirmed only `.env.example` (placeholder values) was ever committed. A full-history grep for the actual real credential values found zero matches anywhere.

**Where it lives in code:** `.gitignore`; `scripts/sync/sync_step1.py` (removed); `storage/` (three directories removed).

**Status:** complete.

---

## main.py becomes the single end-to-end pipeline entry point

**What was decided:** `main.py`'s original content (the Yahoo sync call) moved unchanged to `scripts/sync/sync_yahoo.py`. A new `scripts/detection/run_detection.py` runs the full curated-layer detection pipeline in dependency order (feature engineering → SMC zones → CRT → liquidity sweeps → volume profile → divergence → inter-market divergence → HTF bias), for both symbols, stopping immediately on the first failure. The new `main.py` chains three stages — MT5 sync (gold + eurusd, m5/m15/h1) → `sync_yahoo.py` → `run_detection.py` — each as a subprocess of the existing standalone script, again stopping on first failure, with per-stage progress and a final pass/fail summary. All 8 individual `run_*.py` scripts are untouched and still independently runnable for debugging a single stage.

**Why:** before this, running the whole pipeline meant manually invoking ~10 separate scripts in the right order with the right arguments — easy to get wrong (see the stale-duplicate-upsert bug from Pass C, caused by exactly this kind of manual sequencing gap). Checked first, not assumed: confirmed via grep that Airflow's DAG does *not* call `main.py` at all — it imports `QuantBackend` directly and calls `sync_all()` itself — so moving `main.py`'s content elsewhere required zero DAG changes.

**Evidence:** stop-on-failure was verified directly, not just inferred from the happy path — a deliberately-failing stage was injected into both `run_detection.py`'s and `main.py`'s control flow via monkeypatched subprocess calls, confirming later stages genuinely never run once an earlier one fails. Real end-to-end run of `python main.py` completed successfully end to end against live MT5 + Yahoo data, producing the same row counts as running each stage manually.

**Where it lives in code:** `main.py`, `scripts/sync/sync_yahoo.py`, `scripts/detection/run_detection.py`.

**Status:** complete.

---

## h6 CRT Equilibrium: reinstated after an undecided silent gap was found

**What was decided:** `run_crt_detection.py --timeframe h6` and `run_detection.py`'s CRT stage now run h6 alongside h4 (both, not one replacing the other), and the dashboard's timeframe selector (`dashboard/1_chart.py`) exposes `6h` as a chartable option — matching the original plan's intent for h6 as an intermediate HTF equilibrium read between h4 and d1. Since `raw_<symbol>.h6` is never populated by any sync job (h4/d1 come from Yahoo, h1 from MT5, nothing fetches h6 directly — `quant_backend.py`'s own comment already said this), both `run_crt_detection.py` and the dashboard now resample h1→h6 on the fly via `analysis/features/indicator_features.py::resample_ohlc()`, the same function `run_feature_engineering.py` already used for h6 features — rather than reading from the empty raw table.

**Why:** a routine dashboard-bug audit (grepping "h6" across the whole codebase to check whether a visual issue was h6-related) surfaced a gap nobody had actually decided on: `features` computed h6 for real on every pipeline run (Phase 2c's on-the-fly-resample decision, working as designed), but CRT Equilibrium — h6's other originally-planned consumer per the Phase 2b docstring ("Equilibrium reads whatever timeframe (h4/h6/d1) is requested") — had the code path (`calc_equilibrium()`, `run_crt_detection.py`'s `--timeframe h6` CLI choice) but was never actually invoked by `run_detection.py`, which only ever called `--timeframe h4`. Confirmed via `SELECT DISTINCT timeframe FROM crt_signals`: zero h6 rows existed before this fix, for either symbol. Nobody chose to skip h6 for CRT on purpose — it just never got wired in when `run_detection.py` was written, and the dashboard never offered h6 as a chart timeframe either (checked git history back to the original AnaDashboard commit: h6 was never in `TF_MAP`, consistent with there being no raw OHLC to draw, not a regression). This kind of undecided gap — code exists and works generically, pipeline just never calls it — is exactly the class of thing worth recording once found, rather than leaving it to be silently rediscovered (or silently assumed intentional) later. See also the "Data Integrity Checks" section of `README.md` for the general grep-then-verify-actual-invocation methodology used to find this.

**Evidence:** after wiring in, ran `run_crt_detection.py --timeframe h6` for both symbols live: gold produced 2,077 equilibrium rows (h1 2024-09-13 → 2026-08-14, matching the same h1 range `features` already resamples from), eurusd produced 2,090. `curated_gold.crt_signals` now has `h4`: 3,710 rows and `h6`: 2,077 rows coexisting (both present, neither replaced the other, per the decision). Spot-checked the math on a real row: gold h6 bar 2026-08-14 18:00 — range_high=4396.60, range_low=4370.92, equilibrium=(4396.60+4370.92)/2=4383.76 (exact), close=4376.20 < equilibrium → `discount` bias, correctly classified. Confirmed live in the dashboard: selecting XAUUSD + `6h` renders real resampled candles with CRT/SMC overlays intact, not an empty chart.

**Where it lives in code:** `scripts/detection/run_crt_detection.py` (h6 resample branch + `resample_ohlc` import), `scripts/detection/run_detection.py` (added `CRT (h6)` stage alongside the existing `CRT (h4)` stage), `dashboard/1_chart.py` (`TF_MAP`/`TF_ROW_LIMIT` gained `"6h": "h6"`, load-data branch resamples h1 when `table == "h6"`).

**Status:** complete.

---

## h4 switched from Yahoo-sourced to MT5-resampled (same approach as h6)

**What was decided:** `raw_gold.h4`/`raw_eurusd.h4` (Yahoo `GC=F`/`EURUSD=X`, 4h interval) are deprecated as a data source. `run_feature_engineering.py`, `run_crt_detection.py`, and the dashboard's h4 chart branch now all resample h4 from MT5-sourced `raw_<symbol>.h1` on the fly via `resample_ohlc()`, exactly mirroring the pattern h6 already used (see the entry above). `quant_backend.py`'s Yahoo sync no longer fetches h4 at all (`GOLD_EURUSD_TF` narrowed to `{"d1": "1d"}`); the old `h4` tables still exist with their historical Yahoo rows but nothing reads or writes them anymore. d1 was investigated as part of the same audit and confirmed to have no equivalent problem — left untouched, not revisited by this decision.

**Why:** this started as a routine feasibility audit of switching h4 from Yahoo to MT5 (matching h6's precedent), but turned up a genuine, previously-unknown data-integrity bug as a bonus finding: Yahoo's h4 candle boundaries are anchored to `America/New_York` local time, not fixed UTC, so the boundary silently shifts by an hour whenever US clocks change for DST. Checked empirically against `raw_gold.h4`'s actual timestamps: 27.8% of gold's h4 rows sat on a DST-shifted hour grid every November-March window, meaning the "4h buckets" straddled different real UTC time spans depending on the time of year — a systematic misalignment, not noise. A cost/benefit pass showed switching was near-zero-cost: nothing in `htf_bias_engine.py` or any divergence model (`run_divergence_detection.py`'s `--timeframe` choices are `m5`/`m15`/`h1` only; intermarket divergence runs on h1/d1) reads h4 at all — CRT Equilibrium and the dashboard chart are h4's only two consumers, and CRT Equilibrium already had a resample-from-h1 code path ready to reuse from the h6 work. Three options were considered: (A) full switch to MT5-resampled h4 (chosen — permanently fixes the DST misalignment, matches h6's precedent, trivial implementation cost since the resample plumbing already existed); (B) keep Yahoo h4 but correct its DST anchoring in the fetcher (rejected — more code to maintain for a source that's already redundant now that MT5 covers the same window, and still wouldn't unify the day-boundary conventions the way resampling does); (C) leave Yahoo h4 as-is (rejected — knowingly leaving a confirmed, quantified data-integrity bug in place with a free fix available was not acceptable).

**Trade-off accepted:** the resampled h4 chart's date range is now capped to MT5 h1's own depth (~2024-09-13 onward for both symbols) instead of old Yahoo h4's deeper history (back to ~2024-03/2023-10). This is a cosmetic dashboard-only impact — confirmed no detection/scoring logic depends on pre-2024-09 h4 data — and was accepted as the cost of a permanently-correct UTC grid going forward.

**Evidence:** `run_feature_engineering.py --timeframes h4` and `run_crt_detection.py --timeframe h4` were re-run live for both symbols against real MT5-derived h1 data: gold produced 3,063 h4 feature rows and 3,063 CRT equilibrium rows (h1 2024-09-13 → 2026-08-14 resampled to 4h); eurusd produced 3,082 of each. All pre-existing Yahoo-era rows in `curated_gold`/`curated_eurusd` `features(h4)` and `crt_signals(h4, equilibrium)` were identified and removed by computing the exact valid `bar_datetime` set from the current h1 data directly in Python (more precise than an hour/date-range heuristic, which initially missed 6 EURUSD holiday-gap rows) and deleting anything not in that set — final row counts for both tables now match exactly (gold 3,063/3,063, eurusd 3,082/3,082, no orphans). Spot-checked CRT equilibrium values old vs. new for both symbols: values differ by a sane, comparable magnitude given the changed UTC grid (gold ~46-57 points on a ~4,400 price level; eurusd ~0.00008 on a ~1.157 price level), not wildly divergent or corrupted. Re-ran `run_htf_bias_detection.py` for both symbols end-to-end against the new h4 data: both completed cleanly with no errors, correctly picked up the new row counts ("3063 CRT equilibrium rows (h4)" / "3082 CRT equilibrium rows (h4)"), and produced sane bias distributions. Confirmed live in the dashboard: selecting `4h` for both XAUUSD and EURUSD renders real resampled candles with CRT/SMC/FVG overlays intact, with the expected shorter date range starting ~Sep/Oct 2024 instead of the old deeper Yahoo history.

**Where it lives in code:** `scripts/detection/run_feature_engineering.py` (generic `RESAMPLE_RULE = {"h4": "4h", "h6": "6h"}` dict replacing the h6-only special case), `scripts/detection/run_crt_detection.py` (same `RESAMPLE_RULE` pattern in the Equilibrium branch), `dashboard/1_chart.py` (same pattern in the chart data-loading branch), `scripts/sync/quant_backend.py` (`GOLD_EURUSD_TF`/`GOLD_EURUSD_PERIOD` narrowed to d1-only, docstring documents the deprecation), `scripts/diagnostic/resync_intraday_pass_b.py` (docstring note added marking its gold_h4/eurusd_h4 steps stale, left otherwise unedited as a historical diagnostic tool).

**Status:** complete.

---

## 2-year rolling window default for divergence models, backtest runs, and dashboard aggregates

**What was decided:** every "load full history, no date bound" query feeding divergence models (technical + intermarket), the two backtest scripts, `dashboard/pages/5_backtest_results.py`'s trade load, `dashboard/1_chart.py`'s h1/h4/h6/d1 chart branches, and the htf_bias/ltf_trigger/structural_tp detection scripts that feed those pages now defaults to the most recent 2 years (`WHERE date >= today - 730d`) via a single shared helper, `analysis/rolling_window.py::rolling_window_start()`. This is a calculation/display default, not a deletion — every raw and curated table is untouched; the filter lives entirely at the query layer and the window (`ROLLING_WINDOW_DAYS`) is a one-line change to widen, narrow, or remove later.

**Why:** the user wants current-regime relevance (gold's 2024-2026 run trades very differently from its multi-decade history) prioritized over long-history statistical power for the default view/calculation, while keeping full history available in the DB for anyone who wants to query it directly. Rather than sweep every query silently, a full inventory of every unbounded query across divergence/backtest/dashboard was compiled and presented to the user first (grouped by category, with the ones already date-filtered or point-lookups called out as not needing a change) — the user then explicitly confirmed applying the window to the entire list, including `run_structural_backtest.py`'s raw-bars load whose 70/30 OOS split cutoff is now also computed within the 2-year window rather than full history (confirmed explicitly, since this redefines what "held-out test period" means going forward, not just the full-period stats).

**Evidence:** technical divergence (rsi/obv/stochastic/cci, h1-based) showed **no count change** after the switch — MT5 h1 data itself only goes back to 2024-09-13 (~23 months), already inside the 2-year window, so this is a real, verified non-effect for that half of the divergence suite, not an oversight. Intermarket divergence (d1-based, drivers with much longer native history) showed the expected large reductions since driver histories span years-to-decades: `xau_dxy` 413→27, `xau_us10y` 525→40, `xau_gdx` 171→12, `cot_gold` 359→42, `xau_spdr` 379→25, `xau_gpr` 608→39, `xau_xag` 263→19, `xau_tips` 402→36, `xau_fedfunds` 359→15, `xau_cpi` 233→16, `eur_dxy` 234→10, `cot_eur` 645→49, `eur_yield_spread` 483→37. The two previously-flagged weak/theory-based models (`xau_fedfunds`, `xau_cpi`) shrank the most in absolute terms since their FRED source series are the longest-history drivers — their already-weak, theory-based status (see the "spurious correlation" finding from the intermarket-divergence-buildout phase) is unchanged by this, just recomputed on fewer, more recent signals. `run_htf_bias_detection.py` re-ran clean with identical output (again because h1 is already inside the window). Dashboard confirmed live: 1D chart (previously full history back to ~2000) now starts ~Sep 2024; 4h/1h charts unaffected (already inside window); weekly/monthly backtest breakdown (built same session) unaffected since `backtest_trades` itself only spans the recent structural-TP era.

**Known follow-up, not yet resolved:** the intermarket divergence re-run only `INSERT ... ON DUPLICATE KEY UPDATE`s rows for signals still produced within the new 2-year window — it does not delete the now-orphaned pre-window signal rows already sitting in `curated_*.divergence_signals` from prior full-history runs (e.g. gold's old count of 413 `xau_dxy` rows minus the new 27 leaves ~386 stale rows still in the table). Whether to clean these up (same exact-set-diff method used for the h4 orphan cleanup) is an open question for the user, not yet decided — flagged rather than silently left or silently deleted.

**Where it lives in code:** `analysis/rolling_window.py` (new, shared `ROLLING_WINDOW_DAYS`/`rolling_window_start()`), `scripts/detection/run_divergence_detection.py`, `scripts/detection/run_intermarket_divergence_detection.py`, `scripts/detection/run_htf_bias_detection.py`, `scripts/detection/run_ltf_trigger_detection.py`, `scripts/detection/run_structural_tp.py`, `scripts/backtest/run_structural_backtest.py`, `scripts/backtest/compare_structural_tp_variants.py`, `dashboard/1_chart.py` (`ROLLING_WINDOW_TF` set gating the h1/h4/h6/d1 branches), `dashboard/pages/5_backtest_results.py` (`load_trades()`).

**Status:** implemented and validated; orphaned pre-window signal-row cleanup resolved as a side effect of the d1 MT5-migration entry below (all 13 intermarket divergence models' tables were re-cleaned there using the corrected exact-diff method).

---

## d1 switched from Yahoo-sourced to MT5-resampled — full MT5 migration closed

**What was decided:** `raw_gold.d1`/`raw_eurusd.d1` (Yahoo `GC=F`/`EURUSD=X`, daily interval) are deprecated as a data source, the same way h4 was. `run_feature_engineering.py`, `run_crt_detection.py`, and `dashboard/1_chart.py`'s `1D` chart branch now resample d1 from MT5-sourced `raw_<symbol>.h1` via `resample_ohlc(rule="1d")`, joining the existing `RESAMPLE_RULE = {"h4": "4h", "h6": "6h", "d1": "1d"}` dict. `run_intermarket_divergence_detection.py`'s `load_primary_d1_close()` — the one query with real production impact, since all 13 intermarket divergence models use the symbol's own d1 close as their primary series — switched from a raw-table read to the same resample. `quant_backend.py`'s `GOLD_EURUSD_ASSETS`/`GOLD_EURUSD_TF`/`GOLD_EURUSD_PERIOD` and `_sync_gold_eurusd()` were removed entirely (along with the now-unused `self.yahoo` `YahooFinanceClient` instance) — Yahoo sync for gold/eurusd is fully retired, `_sync_macro()` (DXY/US10Y/VIX/GDX/Silver/FRED/ECB/GPR) is untouched. This closes the full MT5 migration for XAUUSD/EURUSD: every timeframe (m5/m15/h1/h4/h6/d1) is now MT5-sourced or MT5-resampled; Yahoo is scoped purely to macro drivers with no MT5 equivalent. `raw_gold.d1`/`raw_eurusd.d1` still exist with their old Yahoo-sourced rows (not deleted, just no longer written to or read from).

**Why:** the earlier decision to keep d1 on Yahoo specifically cited preserving deep history (26 years vs MT5's ~2 years) as the reason not to switch — but the 2-year rolling window (see the entry above) is now the system-wide default for divergence/backtest/dashboard, so that history is no longer actually used by anything in practice, removing the one reason d1 differed from h4. Investigated before implementing, mirroring the h4 process: (1) traced every d1 consumer — all 13 intermarket divergence models use it as their primary series, `run_feature_engineering.py` computes d1 features by default in the live pipeline, `run_crt_detection.py --timeframe d1` and `run_smc_zone_detection.py --timeframe d1` exist as CLI options but are not invoked by `run_detection.py`'s actual pipeline (same "exists but not wired in" situation h6 was in before being fixed); (2) checked for the same DST-anchoring bug found in h4 — confirmed present and worse: `raw_gold.d1` had 36.1% of rows on a shifted hour grid (hour=5 Nov-Mar vs hour=4 Apr-Oct, America/New_York-anchored), `raw_eurusd.d1` had 58.3% (hour=23 vs hour=0, straddling UTC midnight); (3) proposed resample-from-h1 over a native MT5 D1 fetch, reusing the proven `RESAMPLE_RULE` plumbing instead of adding a new fetcher code path for a mathematically identical result. Findings were reported and the switch confirmed before implementation, same as h4.

**Evidence:** `run_feature_engineering.py --timeframes d1` re-run live for both symbols: gold 6,513 old Yahoo-era rows → 599 fresh MT5-resampled rows (2024-09-13→2026-08-14), eurusd 5,877 → 601. `run_intermarket_divergence_detection.py --model all` re-run for all 13 models: `xau_dxy` 38, `eur_dxy` 6, `xau_us10y` 45, `xau_gdx` 19, `cot_gold` 45, `cot_eur` 55, `xau_spdr` 33, `xau_gpr` 49, `xau_xag` 22, `xau_tips` 40, `xau_fedfunds` 14, `xau_cpi` 14, `eur_yield_spread` 43 — all loaded 599/601 merged bars on the corrected UTC-midnight grid. Orphan cleanup (same exact-valid-set-diff method as h4, this time using `.dt.strftime()` instead of `.astype(str)` after the first cleanup pass — documented as an error below — silently truncated the time component on all-midnight datetime columns and produced false stale-matches) confirmed zero orphans remain in either `features(d1)` or all 13 `divergence_signals` d1 rows. Spot-checked resampled bars two ways: (1) exact match against a manual re-aggregation of the same day's raw h1 rows (gold 2026-08-10: open=4333.01/high=4402.74/low=4313.33/close=4402.36, matched exactly); (2) sanity comparison against the old Yahoo d1 row for the same calendar date — gold differed by single-to-double-digit dollars (different window boundary, NY 4am-anchored vs UTC-midnight), eurusd differed by ~0.0002-0.0009 — both sane, comparable magnitude, not corrupted. Dashboard confirmed live: `1D` chart renders real MT5-resampled candles for both XAUUSD and EURUSD with the correct price scale and the expected ~2-year range (Oct 2024 onward) instead of the old deep Yahoo history. `run_htf_bias_detection.py` re-ran clean for both symbols with identical row counts and no errors (htf_bias doesn't consume d1 directly, only h4 CRT equilibrium, so no regression was expected or found).

**Error caught and fixed during this work:** the first orphan-cleanup pass used `.astype(str)` on the resampled `price_datetime`/`bar_datetime` pandas columns to build the "valid" comparison set. For an all-midnight datetime column, pandas' `astype(str)` silently drops the `00:00:00` time component (producing `"2026-08-14"` instead of `"2026-08-14 00:00:00"`), while the DB-side values (formatted via `datetime.datetime.strftime`) kept the full timestamp — so every comparison mismatched and the cleanup script deleted every row it should have kept, including the freshly-inserted ones, in both `features(d1)` and all 13 `divergence_signals` d1 tables. Caught immediately by the delete count (100% deleted where partial-or-zero was expected), fixed by re-running the detection scripts to restore the fresh rows and redoing the diff with `.dt.strftime('%Y-%m-%d %H:%M:%S')` on both sides for a guaranteed-matching format. Final counts were verified correct after the fix (599/601 features rows, 38/6/45/19/45/55/33/49/22/40/14/14/43 divergence rows, zero orphans) — recorded here rather than silently smoothed over, consistent with this project's "log what actually happened" discipline.

**Where it lives in code:** `scripts/detection/run_feature_engineering.py`, `scripts/detection/run_crt_detection.py` (`RESAMPLE_RULE` dict gained `"d1": "1d"` in both), `scripts/detection/run_intermarket_divergence_detection.py` (`load_primary_d1_close()` rewritten to resample MT5 h1 instead of reading `raw_<symbol>.d1`), `dashboard/1_chart.py` (same `RESAMPLE_RULE` addition), `scripts/sync/quant_backend.py` (`GOLD_EURUSD_ASSETS`/`GOLD_EURUSD_TF`/`GOLD_EURUSD_PERIOD`/`_sync_gold_eurusd()`/`self.yahoo` all removed).

**Status:** complete — full MT5 migration for XAUUSD/EURUSD (m5/m15/h1/h4/h6/d1) closed. Yahoo's remaining scope is macro drivers only (DXY/US10Y/VIX/GDX/Silver/FRED/ECB/GPR), none of which have an MT5 equivalent.

---

## Silver, DXY, VIX migrated from Yahoo to MT5 (US10Y, GDX confirmed to have no MT5 equivalent)

**What was decided:** three of the five Yahoo-sourced macro drivers moved to MT5, on a live availability check (not assumed) against the connected Eightcap terminal (account 5124984, server `EightcapGlobal-Live`, 844 symbols): Silver → `XAGUSD`, DXY → `USDX`, VIX → plain `VIX` (not `VIXUSD`, which is disabled, or `SPXVIX`, a pair). US10Y and GDX were confirmed to have no MT5 equivalent — no bond/yield instrument exists in any category (Commodities/Forex/Indices/Stock/Crypto), and no gold-miner ETF exists among Eightcap's 30 US-listed ETFs — so both stay Yahoo-sourced (`^TNX`, `GDX`) permanently, a category mismatch rather than a migratable gap. `fetcher/market_fetcher.py`'s `MACRO_SYMBOLS`/`MACRO_ASSET_TF` narrowed to US10Y/GDX only. New `h1` tables added to `raw_dxy` (already had one, previously Yahoo-sourced), `raw_vix`, and `raw_silver`, backfilled via `MT5DataFetcher` (same fetcher class gold/eurusd/h4/h6/d1 already use) and kept current going forward by extending `scripts/sync/scheduler/mt5_sync_service.py`'s `RAW_DB` dict with `XAGUSD`/`USDX`/`VIX` (H1-only sync for these three — no m5/m15 tables exist for macro drivers and nothing downstream needs finer than H1). `run_intermarket_divergence_detection.py`'s `xau_dxy`/`eur_dxy`/`xau_xag` driver loaders now resample d1 from that MT5 h1 (`_load_driver_from_h1()`, mirroring `load_primary_d1_close()`'s existing pattern) instead of reading the deprecated Yahoo `raw_dxy.d1`/`raw_silver.d1` tables. VIX has no divergence model in `INTERMARKET_MODELS` currently, so its migration only affects the raw sync layer, not detection.

**Why:** this closes out the two Yahoo-availability questions raised by the Yahoo Source Audit — Silver was already flagged as the highest-priority candidate (same tradeable-metal category as gold), and the audit's live terminal check additionally found `USDX`/`VIX` resolve and trade on Eightcap, which wasn't assumed going in (the audit's own framing was "DXY: is there an Eightcap-tradeable USD index CFD, or only currency pairs?" — answered empirically, not from a broker's marketing page). The 2-year rolling window (see the earlier entry) made the original objection to migrating moot: USDX/VIX have shallower MT5 history than gold/eurusd/silver (added to the terminal more recently — confirmed directly via `copy_rates_from_pos`, not assumed to match), but at 28,548/28,348 h1 bars back to 2021, both comfortably exceed the ~2-year window's actual need by roughly 4x.

**Evidence:** H1 depth confirmed live before implementing, not assumed: XAGUSD 55,990 bars (back to 2003-05-22), USDX 28,548 bars (back to 2021-06-10), VIX 28,348 bars (back to 2021-05-28) — all far exceeding the 2-year window. Backfill ran cleanly for all three (`raw_silver.h1`: 0→12,972 rows; `raw_vix.h1`: 0→11,927; `raw_dxy.h1`: cleaned of its pre-existing Yahoo-sourced rows first — see error note below — then rebuilt to 12,096 MT5-only rows). `mt5_sync_service.py --once` smoke-tested for all three symbols post-change: each connected, calibrated the broker-UTC offset, and incrementally upserted new H1 bars with no errors. Intermarket divergence re-run for the three affected models: `xau_dxy` 38→42, `eur_dxy` 6→24, `xau_xag` 22→20 (small, sane shifts from the corrected UTC grid and new driver source, not corruption) — all orphaned pre-migration rows cleaned via the exact-valid-set-diff method (7/1/7 stale rows removed respectively, final counts match the fresh detect exactly). Spot-checked resampled values against the old Yahoo d1 rows for the same calendar window: DXY (Yahoo Aug 10 close 99.81 vs MT5 Aug 9/11 closes 99.57/99.61) and Silver (Yahoo Aug 10 close 65.11 vs MT5 Aug 9/11 closes 63.53/63.36) both landed in a comparable, sane range — not identical (different source, different window boundary) but not wildly divergent either. `run_htf_bias_detection.py` re-ran clean for both symbols with byte-identical row counts (11,343/11,928) — expected and confirmed, since `htf_bias_engine.py` only consumes the four h1-technical divergence types (rsi/obv/stochastic/cci), not intermarket ones, so this migration cannot regress it.

**Error caught and fixed during this work:** `raw_dxy.h1` was not actually MT5-exclusive before this migration the way gold/eurusd's h1 always was — `market_fetcher.py` had been fetching DXY's h1 from Yahoo too (per the old `MACRO_ASSET_TF = {"DXY": ["h1", "d1"], ...}`), so the initial backfill merged fresh MT5 rows into a table that already held old Yahoo-sourced rows, with no `data_source` column to tell them apart. A first attempt to clean the old rows out by re-fetching from MT5 and diffing exact timestamps against the DB failed the same way the earlier d1-orphan-cleanup attempts did, but for a new reason this time: `MT5DataFetcher`'s broker-UTC-offset calibration is re-measured on every call (by design, so it self-corrects across DST transitions), which bakes a few seconds of run-to-run jitter into every returned bar's timestamp — so a fresh re-fetch's timestamps never exactly match what an earlier fetch already wrote to the DB, even for the identical underlying bar. The diff found 100% of rows "stale" and deleted the entire table, including the just-inserted correct rows. Caught immediately by the same 100%-deleted red flag as before, fixed by simply re-running the backfill for USDX alone against the now-empty table — which, since the old Yahoo rows were also gone at that point, incidentally produced exactly the clean MT5-only end state the migration wanted. Recorded here per this project's "log what actually happened" discipline, same as the earlier `.astype(str)` truncation error.

**Where it lives in code:** `fetcher/market_fetcher.py` (`MACRO_SYMBOLS`/`MACRO_ASSET_TF` narrowed to US10Y/GDX), `scripts/sync/scheduler/mt5_sync_service.py` (`RAW_DB` gained `XAGUSD`/`USDX`/`VIX`, `TIMEFRAMES` scoped to H1-only for macro symbols, `upsert_rows()` branches on whether the target table has a `data_source` column), `scripts/detection/run_intermarket_divergence_detection.py` (`RESAMPLED_H1_DRIVERS` dict + `_load_driver_from_h1()`), `storage/schema_raw.sql` (`h1` tables added to `raw_vix`/`raw_silver`, `pipeline_status` tables added to `raw_dxy`/`raw_vix`/`raw_silver` so a fresh deployment gets what this migration required live).

**Status:** complete and validated. Step 2 (fixing the DST-anchoring and row-duplication bugs on whatever stays Yahoo-sourced — US10Y, GDX, and the now-deprecated Silver/DXY/VIX Yahoo history) is a separate, not-yet-implemented decision — see the audit and the next entry for the root-cause investigation.

---

## DXY/US10Y/VIX/GDX row-duplication cleaned up; US10Y/GDX hardened against recurrence

**What was decided:** the near-total row-duplication found by the Yahoo Source Audit in `raw_dxy.d1`, `raw_us10y.d1`, `raw_vix.d1`, and `raw_gdx.d1` was cleaned up — for every date carrying two rows, the naive-local-time row (`HOUR(price_datetime)=0`) was deleted and the correctly-UTC-converted row (`HOUR(price_datetime)` matching the ticker's real exchange offset, DST-dependent) was kept. `raw_us10y` and `raw_gdx` — the two drivers with no MT5 equivalent, confirmed permanently Yahoo-sourced by the same audit — additionally got a new `UNIQUE KEY uq_date (price_date)` alongside the existing `uq_dt (price_datetime)`, so a future accidental re-introduction of a differently-labeled row for an already-synced date now upserts in place instead of silently duplicating. `raw_dxy`/`raw_vix` (deprecated as of the prior Silver/DXY/VIX MT5-migration entry, no longer written to) were cleaned for historical-data hygiene but did not get the `uq_date` hardening, since nothing will ever sync into them again. `raw_silver.d1` needed no duplicate cleanup — confirmed via the original audit to have zero duplicate dates, meaning its history was apparently only ever synced post-fix.

**Root cause, investigated before fixing (not assumed):** `fetcher/timezone_utils.py`'s own docstring documents a real historical bug — an earlier version of every Yahoo-sourced fetcher in this project stripped tzinfo without first converting to UTC (`.tz_localize(None)` or a bare `.strftime()` on a tz-aware index), silently writing exchange-local wall-clock time into the DB as if it were UTC. `to_utc_naive()` in that same file is the fix, and `market_fetcher.py`'s `fetch_market_data()` already calls it on every fetch. The schema's unique key is on `price_datetime` alone, not `price_date` — so when the fix was deployed, the next full-history sync (`period="max"`, which refetches all history every run) wrote a second, correctly-converted row for every date a pre-fix run had already written a naive one for; neither collided as a duplicate key since the hour differs, so both survived. Confirmed directly, not inferred: the most recent 5 dates in `raw_dxy.d1` (added after the fix, never touched by any pre-fix run) had only the single correct row before cleanup, while the other 14,000+ dates all had exactly 2 — proof this is leftover historical contamination, not an active bug. Also confirmed the naive/correct rows are true duplicates, not independently-fetched different data: GDX had 4 date-pairs (out of 5,085) with penny-level OHLC differences, individually inspected and found to be ordinary Yahoo data revisions between fetch runs, not a different bug class.

**Evidence:** row counts before/after cleanup — `raw_dxy.d1` 28,239→14,122 (14,117 deleted), `raw_us10y.d1` 32,279→16,142 (16,137 deleted), `raw_vix.d1` 18,441→9,223 (9,218 deleted), `raw_gdx.d1` 10,175→5,090 (5,085 deleted) — every `after` count matches that table's previously-confirmed distinct-date count exactly, and a follow-up query confirmed zero remaining duplicate dates in all four. Verified against live data before deleting, not just internally self-consistent: fetched real GDX 2020-06-10 history live via `yfinance` (`2020-06-10 00:00:00-04:00`, America/New_York) — converting to UTC gives `2020-06-10 04:00:00`, which matched the DB's hour=4 row (open 31.085/high 32.050/low 30.110/close 32.050) exactly, not the hour=0 row that was deleted, confirming the keep/delete rule empirically rather than by assumption. Confirmed the going-forward fix needs no code change — a live re-fetch of US10Y/GDX today returned hour=5 (US10Y, Chicago CDT) and hour=4 (GDX, NY EDT) respectively, never hour=0, proving `to_utc_naive()` is already fully active on every current fetch path. Stress-tested the new `uq_date` constraint the same way the original bug occurred: ran a full `period="max"` re-sync of both US10Y and GDX through the real `QuantBackend._sync_macro()` path immediately after adding the constraint — upserted the exact same row counts as already present (16,142 / 5,090) with zero duplication and zero hour=0 rows reappearing, confirming the hardening actually prevents the failure mode it targets, not just in theory. Re-ran the two affected divergence models: `xau_us10y` 45→46, `xau_gdx` 19→17 (small, sane shifts from the corrected driver values, not corruption) — orphaned rows cleaned via the same exact-valid-set-diff method (10/10 stale rows removed, final counts match the fresh detect exactly). `run_htf_bias_detection.py` re-ran clean with an identical row count (11,343) — expected, since it doesn't consume intermarket divergence.

**Where it lives in code:** `raw_dxy.d1`, `raw_us10y.d1`, `raw_vix.d1`, `raw_gdx.d1` (duplicate rows deleted directly), `storage/schema_raw.sql` (`uq_date` added to `raw_us10y.d1`/`raw_gdx.d1`'s `CREATE TABLE`, with a comment explaining why). No application code changed — `fetcher/market_fetcher.py`'s existing `to_utc_naive()` call was confirmed correct as-is, not modified.

**Status:** complete and validated.

---

## HTF Bias Engine audit: xau_fedfunds/xau_cpi already excluded, no gap found

**What was checked:** whether `htf_bias_engine.py`'s hidden/regular divergence contribution pulls in every persisted divergence signal indiscriminately — specifically whether the two intermarket models already flagged as weak/unconfirmed (`xau_fedfunds`, near-zero +0.03 correlation; `xau_cpi`, likely spurious from a shared secular trend) leak into the confluence score the way MTF Alignment Divergence was found to before being excluded.

**What was found:** no gap — both models were already excluded, on two independent dimensions, since the module's original Phase 3a design (before either model existed). `run_htf_bias_detection.py::load_divergence_h1()` queries `WHERE timeframe='h1' AND divergence_type IN ('rsi','obv','stochastic','cci')`; `xau_fedfunds`/`xau_cpi` are stored with `timeframe='d1'` and a `divergence_type` outside that whitelist, so they fail both filters independently, not just one. Traced `calc_htf_bias()`'s hidden/regular divergence logic directly (not just the docstring's claim) and confirmed the `divergence_h1` DataFrame it receives is the only divergence input to the function, sourced exclusively from that already-filtered query — no second, broader path into `divergence_signals` exists anywhere in the component. The module docstring already documented the exclusion of all d1 intermarket divergence (not specific to these two models) with different reasoning than "weak correlation" — "d1 intermarket signals are economically meaningful over weeks, not well-suited to an hourly lookback window" — but the practical effect (zero influence on `htf_bias`) is identical to what excluding them for weak-correlation reasons would have produced.

**Why no fix, no re-run:** the code path in question never read `xau_fedfunds`/`xau_cpi` in the first place, so a re-run would produce byte-identical `curated_gold.htf_bias`/`curated_eurusd.htf_bias` output to what's already persisted — re-running and reporting a diff of zero would not be a meaningful validation step. Recorded here as a "checked, found clean" entry so this exact question doesn't need re-investigating from scratch in a future session.

**Where it lives in code:** nothing changed — `scripts/detection/run_htf_bias_detection.py::H1_DIVERGENCE_TYPES` and `analysis/strategies/htf_bias_engine.py`'s module docstring (lines 41-54) already state and enforce this.

**Status:** confirmed, no action needed.

---

## Structural TP stop capped at MAX_STOP_ATR_MULTIPLE — fixes the R:R skew, does NOT clearly fix the backtest's fragility

**What was decided:** `structural_tp_engine.py`'s stop (still the trigger's own `htf_zone` far edge, `stop_mode='zone_far_edge'`) is now capped at `MAX_STOP_ATR_MULTIPLE = 1.5` × h1 ATR-14 — if the zone's far edge would put the stop further away than that, the stop is pulled in to the cap instead. The zone edge stays the reference for every normal-width zone; only the unusually wide ones get bounded. `STRUCTURAL_TP_FRACTION` (0.85) and the nearest-opposing-zone target-selection logic were left unchanged.

**Why the stop, not the target:** before touching anything, risk (stop distance) and reward (target distance) were measured separately in ATR terms on real XAUUSD data. Risk averaged 1.92x ATR-14 (median 1.69x); reward averaged only 0.55x ATR-14 (median 0.36x) — the stop side was carrying essentially all of the R:R skew (median structural_rr was 0.21, i.e. stops ~4-5x wider than targets), so that's where the fix went. No comparable evidence pointed at the target side, so `STRUCTURAL_TP_FRACTION`/target selection weren't touched, per the user's explicit "confirm, don't assume" framing.

**Why a cap and not a different stop definition:** three options were tested against real data before choosing. (a) Nearest LTF swing that formed the CHoCH — the most textbook-SMC answer, but `SMCStructureEngine.detect_bos_choch()` doesn't currently persist that swing price per trigger, so it would mean re-deriving LTF structure and introduces new unvalidated assumptions (which pivot, wick vs. close) for an untested payoff — not pursued this pass. (b) Replace the zone stop entirely with a pure ATR multiple (`stop_mode='atr'`, already existed for the variant-comparison script) — tested 1.0/1.5/2.0/2.5x on real data; 1.0x gave the single best median R:R (0.21 → 0.37) but abandons "the zone that produced the signal is what invalidates it" — the same reasoning that got Option 1 (confluence scaling) rejected when this engine was designed. (c) Keep the zone stop, cap it at an ATR multiple — chosen: it's a numerical-safety bound on an existing structural read, the same class of fix `MIN_RISK_ATR_MULTIPLE` already established for the floor side, not a new performance-fitted parameter. Tested caps 1.5/2.0/2.5/3.0x; 1.5x gave the best real median improvement (0.21 → 0.28, +33%) while being the most conservative (tightest) of the caps tested, so it's the one used — flagged as a starting point, not a settled constant, same status as `STRUCTURAL_TP_FRACTION`.

**Evidence — R:R distribution, XAUUSD choch_only (n=2217 structural triggers, unchanged by the fix since the cap never skips a trigger, only tightens its stop):**

| | min | 25th | median | 75th | max |
|---|---|---|---|---|---|
| before (zone_far_edge, uncapped) | 0.001 | 0.091 | 0.210 | 0.486 | 4.628 |
| after (capped at 1.5x ATR) | 0.001 | 0.129 | 0.278 | 0.581 | 4.628 |

Max is unchanged because that specific outlier trigger's own zone-derived risk was already tighter than 1.5x ATR — the cap only engages on the wide-zone tail, exactly as designed, and doesn't touch triggers that were already reasonably sized.

**Evidence — did this fix the backtest's "win often, lose big" fragility? Checked, not assumed — and the honest answer is no, not clearly.** Re-ran the full structural backtest for both symbols, both modes, both periods (8 runs total). Win rate fell in all 8 (roughly 3-5 points, e.g. XAUUSD choch_only full 80.3%→77.0%) — tighter stops get clipped by ordinary noise more often, which is the expected trade-off of tightening a stop. Expectancy was a wash: up in 4 of 8 cuts, down in 4 of 8, all by small amounts (XAUUSD choch_only full 0.058R→0.063R; XAUUSD choch_sweep full 0.090R→0.072R). Max drawdown got **worse** in 6 of 8 cuts, sometimes substantially — XAUUSD choch_sweep full 6.46R→9.14R, EURUSD choch_only full 5.80R→8.66R — because a run of ordinary noise-driven stop-outs now costs the same -1R each but happens more often. Sharpe/deflated-Sharpe moved in step with expectancy, i.e. also a wash. **Conclusion: the stop-cap is a correct, verified fix for the R:R-skew problem it targeted, but it trades win-rate and drawdown against R:R gain roughly evenly — it does not, on this data, resolve the underlying fragility the earlier backtest flagged.** That's a different, harder problem (likely closer to entry/exit timing or the CHoCH trigger definition itself than to stop placement) and out of scope for this pass, which was scoped to stop/target calculation only.

**Where it lives in code:** `analysis/strategies/structural_tp_engine.py` (`MAX_STOP_ATR_MULTIPLE` constant, cap logic in `compute_structural_targets()`'s `zone_far_edge` branch, module docstring's new "Maximum stop-distance cap" section), `scripts/detection/run_structural_tp.py` (prints the new constant alongside the existing two). `backtest_runs`/`backtest_trades`/`ltf_trigger_signals` re-computed for both symbols, both modes, both periods.

**Status:** implemented and validated; the R:R fix is real, the fragility is not resolved by it — flagged as still open, not silently closed.

---

## Minimum R:R threshold filter explored — no threshold recommended, most fail the statistical floor

**What was tested:** a new exploratory-only script, `scripts/backtest/compare_min_rr_thresholds.py`, layers a `structural_rr >= threshold` filter on top of the already-applied stop-cap fix (previous entry) — rejecting triggers whose calculated R:R is already below a cutoff, rather than taking every structurally-valid trigger. Tested thresholds: no filter (current production), 1.0, 1.5, 2.0, 3.0, across both symbols, both modes, both periods (full/held-out test) — 40 rows total. Mirrors `compare_structural_tp_variants.py`'s pattern exactly: in-memory recomputation, not written back to `ltf_trigger_signals`/`backtest_runs`, same multiple-comparisons caveat, no winner picked.

**Result, no filter (current production baseline) vs rr>=1.0 (the least aggressive filter tested), full-period:**

| symbol/mode | n_decided (no filter → rr≥1.0) | win rate | expectancy_r | max_drawdown_r |
|---|---|---|---|---|
| XAUUSD choch_only | 461 → 103 | 77.0% → 53.4% | 0.063R → 0.281R | 6.98R → 4.02R |
| XAUUSD choch_sweep | 381 → 78 | 77.4% → 53.9% | 0.072R → 0.282R | 9.14R → 3.02R |
| EURUSD choch_only | 543 → 107 | 75.5% → 54.2% | 0.054R → 0.382R | 8.55R → 5.52R |
| EURUSD choch_sweep | 466 → 94 | 76.0% → 58.5% | 0.069R → 0.427R | 8.41R → 3.52R |

Expectancy roughly quadruples to sextuples and drawdown drops substantially at every rr>=1.0 cut — filtering out low-R:R triggers does exactly what the hypothesis predicted, on the trades that remain. But trade count collapses to roughly 17-23% of the unfiltered count doing it, which is where the statistical floor becomes the deciding factor, not the metrics themselves.

**Statistical floor (200 trades/12mo, scaled to period length — 99 for the 180-day full period, 30 for the 54-day test period): only one of the eight symbol/mode combinations clears the floor on BOTH periods at any filtered threshold** — EURUSD choch_only at rr>=1.0 (107/99 full, 39/30 test). Every other combination fails at least one period at rr>=1.0, and every combination fails both periods at rr>=1.5 and above. XAUUSD choch_only at rr>=1.0 is a near-miss: clears full (103/99) but misses test by one trade (29/30). Full per-threshold, per-period floor status is in the script's own output (`BELOW STATISTICAL FLOOR` section, printed automatically, not something to eyeball from the metrics table).

**No threshold is being recommended here** — same discipline as `compare_structural_tp_variants.py`. The pattern is legible enough to state plainly though: the metrics genuinely improve with filtering, but on this ~6-month single-regime dataset, only the least aggressive threshold on one of eight combinations produces a sample size the project's own floor considers reliable. Every more aggressive cut, and every other combination even at the mildest cut, would be reporting metrics computed from too few trades to trust regardless of how good they look.

**Where it lives in code:** `scripts/backtest/compare_min_rr_thresholds.py` (new, exploratory-only, not part of the pipeline). No production code changed — `structural_tp_engine.py`, `run_structural_tp.py`, `backtest_runs` are untouched by this entry.

**Status:** exploratory comparison complete, reported, no decision made.

---

## 3-way (train/validation/test) grid search over LTF trigger/structural-TP parameters — a stricter overfitting control than the earlier 70/30 split

**What was tested:** a new exploratory script, `scripts/backtest/grid_search_structural_tp.py`, sweeps `STRUCTURAL_TP_FRACTION` (0.70/0.85/1.00), `MIN_RISK_ATR_MULTIPLE` (0.3/0.5/0.7), `MAX_STOP_ATR_MULTIPLE` (1.5/2.0/2.5), and `CONFIRMATION_WINDOW_BARS` (10/20/30) together — 81 combinations. Split by calendar time 60/20/20 (train/validation/test), not the plain 70/30 the production backtest uses. Grid-ranked by train expectancy; top 5 evaluated on validation without touching test; single final candidate evaluated once on test with no further iteration. Results and per-combination data written to `docs/optimization_results/` (new directory, timestamped files so re-runs accumulate history instead of overwriting — see that directory's own README).

**Critical correction made before running anything, per this task's own "check the floor first" requirement:** the usable backtest window is NOT the 2-year rolling window used elsewhere in this project — it's bounded by the LTF (m15) raw data's actual depth, which only goes back to 2026-02-15 (~180 days), because `mt5_sync_service.py` only started syncing m15/m5 recently relative to h1. A 60/20/20 split of 180 days gives train=108d (floor=59 trades), validation=36d (floor=20), test=36d (floor=20) — thinner than the "2 years" framing assumed. Checked before running the grid: baseline (current defaults) trade volume comfortably clears all three floors, so the split was used as proposed rather than adjusted further; this was verified, not assumed.

**Scoping decision, reported not silently made:** the full grid was run for XAUUSD/choch_only only. Real per-cell timing (~25s to re-derive LTF trigger structure per `CONFIRMATION_WINDOW_BARS` value, ~5-6s per stop/target+backtest combination) makes all 4 symbol/mode combinations a 30+ minute run; XAUUSD/choch_only alone took ~7 minutes once running correctly. Rerun with `--symbol`/`--mode` for the other three combinations if wanted — not done here.

**Result:** all 81 combinations cleared the train floor (108 days of data is enough even for the tightest grid cells). Current production defaults (fraction=0.85, min_risk=0.5, max_stop=1.5, confirm_window=20) ranked **55th of 81** by train expectancy (0.077R vs the top combination's 0.145R) — below the median, not competitive with the top of this grid on this specific slice of history. The train→validation→test-selected final candidate (fraction=1.0, min_risk=0.3, max_stop=1.5, confirm_window=10) showed expectancy 0.145R (train) → 0.178R (validation) → 0.135R (test) — validation came in *above* train and test landed between the two, the opposite of the blow-up-then-collapse pattern that would signal overfitting. DSR corrected for all 81 trials tested (not just a Mode-A/B pair): 0.894, i.e. an 89.4% probability the true Sharpe exceeds the deflation threshold even after that correction.

**Why this is not a recommendation to change defaults, per this task's explicit framing:** the grid and the split are both drawn from the same single ~180-day, single-regime (gold bull run) history every other exploratory comparison in this project has already been run against — a clean train/val/test result here rules out one specific failure mode (a candidate that only looks good because it was picked to fit train) but does not establish that this parameter combination would hold up in a different market regime, which no amount of splitting the same 180 days can test. Full grid (81 rows × per-split metrics) is in `docs/optimization_results/20260817_093708_XAUUSD_choch_only_grid.csv`; the human-readable version with the full top-10/top-5/final-candidate breakdown is in the paired `_ltf_params.md` file in the same directory.

**Where it lives in code:** `scripts/backtest/grid_search_structural_tp.py` (new, exploratory-only), `docs/optimization_results/` (new directory, gitted). No production code changed.

**Status:** exploratory grid search complete for one of four symbol/mode combinations, reported, no decision made.

---

## Why m15/m5 only have 180/90 days: our own resync tool's lookback, not a broker limit — investigated, backfill not yet implemented

**What was investigated:** the grid search above (and the backtests before it) turned out to be bounded by only ~180 days of LTF data, not the project's usual 2-year window. Two hypotheses were checked before assuming either: (1) Eightcap's own M15/M5 history retention is genuinely that short, or (2) our own sync process never backfilled as deep as what the broker actually retains.

**Finding: (2), confirmed with evidence, not assumed.** Queried MT5 directly for XAUUSD's true earliest available bar per timeframe (via `copy_rates_from()` with progressively older target dates — MT5 keeps returning the same earliest bar once you're past its retention ceiling, which is how the ceiling itself is found): H1 → 2003-05-09 (~23y), M15 → 2022-05-24 (~4.25y), M5 → 2025-03-19 (~1.4y). Compared against what's actually in `raw_gold`/`raw_eurusd`: h1 has ~700 days, m15 has exactly **180 days, 2:30:43**, m5 has exactly **89 days, 2:50:43** — matching `scripts/diagnostic/resync_intraday_pass_b.py`'s hardcoded `MT5_LOOKBACK_DAYS = {"H1": 700, "M15": 180, "M5": 90}` to the hour, for both symbols. That script's own docstring confirms it does a destructive DELETE + full-table replace, and `pipeline_status` confirms its last run (2026-08-15 00:58:42) matches the data's exact cutoff. The broker genuinely retains less history for finer granularities than H1 (a real, unfixable ceiling) — but that ceiling is ~1,550 days for M15 and ~515 days for M5, nowhere near the 180/90 days actually synced. The gap is self-imposed, not broker-imposed.

**Backfill plan proposed, not implemented:** M15 → 2022-05-24 (fully covers the 2-year rolling-window default with over a year of margin, closing the sample-size gap that bounded the grid search above). M5 → 2025-03-19 (broker ceiling, short of 2 years but ~5.7x current depth). Mechanism: `MT5DataFetcher.get_rates(chunk_days=30)`, the same chunked pattern already used for the Silver/DXY/VIX backfill and by Pass B itself — but as an upsert into the existing tables (matching `mt5_sync_service.py`'s own pattern), not a destructive delete-first replace, since there's no reason to disturb the current data while extending it backward. Estimated ~52 chunks (M15) + ~18 chunks (M5) per symbol, no documented rate limit on the local MT5 terminal API (unlike a cloud REST API), expected to complete in well under a few minutes total based on this session's already-observed chunk-fetch timings.

**Also found, not the question asked but relevant:** `mt5_sync_service.py` isn't continuously running/scheduled in this environment — `pipeline_status.last_success_at` is the same 2026-08-15 timestamp across all three timeframes, meaning nothing has synced since, independent of the depth question.

**Where it lives in code:** nothing changed yet — investigation only. Backfill plan targets `scripts/sync/mt5_sync_service.py` or a new one-off backfill script reusing `MT5DataFetcher`, not yet written.

**Status:** investigated and confirmed; backfill plan proposed, awaiting go-ahead to implement.

---

## Full backfill executed: M5/M15 to broker ceiling, H1 to broker ceiling (revised scope)

**What was decided and done:** all three raw timeframes backfilled to their real broker ceiling via `MT5DataFetcher.get_rates(chunk_days=30)`, upserting only the gap between each table's existing earliest row and the target start (not a destructive replace, unlike `resync_intraday_pass_b.py`). M5 and M15 target their own broker ceilings as originally proposed. H1's target was revised mid-implementation: initially proposed capped to match M15's shallower ceiling (2022-05-24) on the reasoning that nothing could pair H1 zones with LTF triggers beyond that depth — the user overrode this, since H1 is the backbone of the whole HTF analysis layer (CRT equilibrium, HTF bias, all divergence models) independent of LTF-trigger pairing, and asked for H1's own full ceiling instead.

**H1 ceiling differs by symbol, confirmed empirically, not assumed to match:** XAUUSD's H1 ceiling is a clean 2003-05-09 (`copy_rates_from()` at any earlier date consistently returns this same bar, no errors). EURUSD's is different and less clean: `copy_rates_from()` returned `(-1, 'Terminal: Call failed')` consistently (3 repeated attempts) for any date at or before 2010-07-01, and consistently succeeded from 2010-07-15 onward — treated as EURUSD's practical ceiling (~2010-07-14, ~16 years) rather than XAUUSD's 23 years. Not the same kind of clean boundary as XAUUSD's (an error return, not an empty-but-successful one), but reproducible across repeated attempts, unlike the transient background-execution issues found elsewhere this session — treated as a genuine per-instrument retention difference.

**Row counts, before → after:**

| table | before | after | true earliest |
|---|---|---|---|
| raw_gold.m5 | 17,873 | 100,004 | 2025-03-19 |
| raw_gold.m15 | 11,846 | 100,010 | 2022-05-24 |
| raw_gold.h1 | 11,343 → 25,050 (M15-aligned step) | **56,017** | 2003-05-11 |
| raw_eurusd.m5 | 18,775 | 99,952 | 2025-04-15 |
| raw_eurusd.m15 | 12,509 | 100,005 | 2022-08-08 |
| raw_eurusd.h1 | 11,928 → 25,024 (M15-aligned step) | **99,927** | 2010-07-15 |

(H1 was backfilled in two steps since the target changed mid-task — first to match M15, then extended to the full ceiling once the scope was revised. Both steps are plain upserts, so the end state is identical to having targeted the final depth directly.) Verified no gap where new and pre-existing data meet: `LAG()`-based gap check found only weekend/holiday-sized gaps (>24h between consecutive bars), consistent with normal market closures, not a sync hole.

**Downstream recompute — traced against actual code, not assumed uniform:** every `run_*.py` detection script was checked for whether it filters to `rolling_window_start()` (the system-wide 2-year default) or reads full raw history unbounded.

- **Filtered to rolling 2-year window (unaffected by this backfill, no recompute needed or useful):** `run_divergence_detection.py`, `run_intermarket_divergence_detection.py`, `run_htf_bias_detection.py`, `run_ltf_trigger_detection.py`, `run_structural_tp.py`, `run_structural_backtest.py`, `dashboard/1_chart.py`, `dashboard/pages/5_backtest_results.py`. These read `WHERE price_datetime >= rolling_window_start()` regardless of how deep the raw table goes — their output is byte-identical whether the raw table has 2 years or 23 years behind that cutoff. No production output changes from this backfill.
- **Unfiltered (read full raw history, benefit from the deeper data once re-run):** `run_feature_engineering.py`, `run_crt_detection.py`, `run_smc_zone_detection.py`, `run_liquidity_sweep_detection.py`, `run_volume_profile.py`.

**Of the unfiltered scripts, only `run_feature_engineering.py` was actually re-run.** Real timing: ~55s per symbol for all six timeframes (m5/m15/h1/h4/h6/d1) — cheap, ran for both symbols, `curated_gold`/`curated_eurusd`.`features` now spans the full backfilled depth (e.g. gold's d1 features: 6,490 rows back to the new h1 floor).

**`run_smc_zone_detection.py` (and by inference the same-shaped `run_crt_detection.py`/`run_liquidity_sweep_detection.py`/`run_volume_profile.py`) were NOT re-run over the full depth — tested, found too expensive for zero production benefit, not silently skipped.** Ran XAUUSD h1 zone detection for real: still running after 10+ minutes (confirmed via `Get-Process` CPU time genuinely climbing in step with wall-clock time — compute-bound, not another instance of this session's earlier background-throttling artifact) against the ~5x larger 56,017-bar h1 table, vs. 54s for the entire feature-engineering pass across all six timeframes combined. Killed rather than let it run further, since `upsert_zones()` only writes once at the end (confirmed in the code before killing) — `curated_gold.smc_signals` is untouched, still reflecting the pre-backfill ~2-year range, no partial-write risk. Not pursuing this further because the payoff is genuinely zero for current production: every consumer of SMC zones (`htf_bias`, `ltf_trigger_signals`, the backtest) already filters to the trailing 2-year window, AND zone detection itself already has its own independent recency bound (`SMC_ZONE_RECENCY_WINDOW_BARS`, added earlier this project specifically because unbounded zone accumulation saturates the SMC-dominant bias score) — a zone from 2005 would never survive long enough to reach a bar from 2026 regardless of whether it's in the table. The only value a full re-run would add is deep-history *availability* for some future exploratory regime-diversity analysis, not anything current — flagged as an open option, not done here given the empirically-confirmed cost.

**Where it lives in code:** raw `h1`/`m15`/`m5` tables for both symbols (backfilled), `curated_gold`/`curated_eurusd`.`features` (recomputed, all six timeframes). No application code changed. No `smc_signals`/`crt_signals`/`liquidity_sweeps`/`volume_profile` recompute performed.

**Status:** raw backfill complete and validated for all three timeframes, both symbols. Feature recompute complete. SMC/CRT/liquidity-sweep/volume-profile deep recompute deliberately not performed — cost confirmed empirically to outweigh benefit for current production use; revisit only if a future need for deep-history SMC/CRT signal validation arises.

---

## Performance bug, logged not fixed: `LTFTriggerEngine.compute_triggers()` scales worse than linearly with bar count

**What was found:** while sizing the aligned train/validation/test grid search below, `compute_triggers()`'s runtime was measured directly at two real data sizes on the same symbol/mode (EURUSD/choch_only/m15, `confirmation_window_bars=20`): 11,846 bars → ~25s, 24,881 bars → 96.2s. That's a ~2.1x increase in bar count producing a ~3.85x increase in runtime — a calibrated power-law exponent of **~1.82** (near-quadratic), not the linear scaling a per-bar pivot/CHoCH-matching pass would be expected to have. An earlier, even larger test (100,005 bars, the full post-backfill M15 history) was still running after 10+ confirmed CPU-bound minutes before being killed — consistent with, not contradicting, the ~1.82 exponent (extrapolating: ~1,780s / ~30min at that size).

**Why this matters going forward, not just for this task:** MT5 history keeps accumulating every day the sync service runs. A near-quadratic cost means the problem gets worse on its own over time, with no code change required to trigger it — a script that takes 25s today against 2 years of data could take tens of minutes against 4 years and multiple hours against 8, even though the underlying task (derive triggers from OHLC structure) has no inherent reason to be worse than linear in bar count. This already forced a real scoping compromise in the grid search below (a ~4-year aligned window had to be shrunk to ~200 days to fit a reasonable runtime budget) and will keep forcing similar compromises on any future exploratory work over the growing raw history, unless fixed.

**Not investigated or fixed here — explicitly out of scope for this task.** Likely culprit (not confirmed): the touch/CHoCH window-matching logic in `ltf_trigger_engine.py` appears to do some form of nested scan per CHoCH event against nearby touch events rather than a single sorted-merge pass, which would explain super-linear scaling, but this is an inference from the symptom, not a code-level diagnosis — flagged for whoever picks this up next, not solved here.

**Where it lives in code:** `analysis/strategies/ltf_trigger_engine.py`'s `LTFTriggerEngine.compute_triggers()` (specifically the touch/CHoCH/sweep matching loop, unconfirmed exact location). No fix applied.

**Status:** documented, not fixed. Revisit if exploratory work needs a bigger raw-history window than the current backfilled depth can support within a reasonable runtime, or if `mt5_sync_service.py`'s continued accumulation makes even production-window (2-year) runs noticeably slow.

---

## Strict time-aligned 3-way grid search across all 4 symbol/mode combinations

**What changed from the earlier single-combination run:** the previous grid search (XAUUSD/choch_only only) let its train/val/test dates fall out of each symbol's own independently-computed max-available range — fine for one combination, but comparing across symbols/modes that way would let a symbol with deeper history claim an unfair sample-size advantage. Re-run with strict alignment: every symbol/mode combination uses the identical calendar dates, hardcoded as module constants (`WINDOW_START`/`TRAIN_END`/`VAL_END`/`WINDOW_END`) in `grid_search_structural_tp.py` rather than derived per-invocation, so they can't silently drift between runs of the same comparison.

**Window sizing, calibrated from real data, not guessed:** the true shared window (bounded by EURUSD's shallower M15 broker ceiling, 2022-08-08 — see the backfill entry above) is ~4 years, but a real timing test found `LTFTriggerEngine.compute_triggers()` scales as ~O(n^1.82) with bar count (see the performance-bug entry above), making the full ~4-year window an estimated 2-4 hours for all 4 combinations. The user asked for the largest window fitting a ~30-45 minute budget, computed from the calibrated exponent rather than guessed: **~200 days lands at an estimated ~37 minutes; actual measured runtime was ~28 minutes for all 4 combinations.** This is well short of the ~12-18 month window originally hoped for — reported as an explicit trade-off before running, not silently substituted.

**Final shared window: 2026-01-27 00:30:43 → 2026-08-15 00:30:43 (200 days).** Split: train 2026-01-27→2026-05-27 (120d, floor=66), validation 2026-05-27→2026-07-06 (40d, floor=22), test 2026-07-06→2026-08-15 (40d, floor=22). Floor clearance confirmed for EURUSD (the binding, shallower symbol) with real trade counts *before* committing to the full grid: train=362, val=115, test=122 — all comfortably above floor.

**Results, all 4 combinations, 81-cell grid each (fraction × min_risk × max_stop × confirm_window):**

| symbol/mode | winning params (fraction/min_risk/max_stop/cw) | train expectancy | val expectancy | test expectancy | DSR (n=81) | defaults' rank/81 |
|---|---|---|---|---|---|---|
| XAUUSD choch_only | 1.0 / 0.3 / 1.5 / 30 | 0.136R | 0.048R | 0.050R | 0.868 | 43 |
| XAUUSD choch_sweep | 1.0 / 0.3 / 1.5 / 20 | 0.175R | 0.088R | 0.089R | 0.934 | 26 |
| EURUSD choch_only | 1.0 / 0.3 / 2.0 / 30 | 0.109R | 0.179R | 0.281R | 0.633 | 33 |
| EURUSD choch_sweep | 1.0 / 0.3 / 1.5 / 20 | 0.142R | 0.174R | 0.220R | 0.565 | 39 |

**The train→val→test pattern is genuinely mixed across symbols — reported plainly, not smoothed into one conclusion.** XAUUSD shows the shape an overfitting check exists to catch: train expectancy roughly 2-3x validation/test, both drop-and-hold at a much lower level (choch_only especially — 0.136R train vs. 0.048-0.050R val/test). EURUSD shows the *opposite* shape on this window: validation and test both exceed train, increasingly so (choch_only test expectancy is 2.6x train). Both are real, measured outcomes from the same methodology applied identically to both symbols — not a case of one symbol being "right" and the other "wrong." Current production defaults rank in the same rough middle-of-pack range (26th-43rd of 81) across all four, consistent with the earlier single-combination finding that defaults aren't near the top of this grid on any of these slices, without being an outlier at the bottom either.

**Where it lives in code:** `scripts/backtest/grid_search_structural_tp.py` (`WINDOW_START`/`TRAIN_END`/`VAL_END`/`WINDOW_END` constants, `load_bars_in_window()` replacing the per-symbol dynamic range computation). Full per-combination reports and raw grid CSVs: `docs/optimization_results/20260817_11{1916,2645}_XAUUSD_*` and `20260817_11{3701,4512}_EURUSD_*`.

**Status:** all 4 combinations complete, strictly time-aligned, reported. No change to production defaults recommended — same as every prior entry in this exploratory series.

---

## Sensitivity + neighbor-stability plots for the strict-aligned grid search

**What was added:** `scripts/backtest/plot_grid_sensitivity.py`, a plotting-only script (reads the raw grid CSVs already written above, recomputes nothing) producing two PNGs per symbol/mode: a 2x2 one-at-a-time sensitivity panel (each parameter swept with the other 3 held at the winning combination's values, train/val/test expectancy as three lines) and a neighbor-stability bar chart (the winner plus every grid cell exactly one parameter-step away). The winner is re-derived from the CSV using the same selection rule the grid search itself uses, not re-typed from the earlier report, so the plotted numbers can't drift from what was already documented. `matplotlib` added to `requirements.txt` — neither it nor `plotly` (already listed there but unused anywhere in the codebase, confirmed by grep) was actually installed or in use; matplotlib was installed fresh since the user's own instructions named it as the default.

**What the plots show, XAUUSD/choch_only (confirms the overfitting signal visually, not just numerically):** every one of the 4 sensitivity panels shows the same shape — the train line moves one direction while val/test move a different direction or stay flat. Most striking: `MIN_RISK_ATR_MULTIPLE` — train rises steeply from 0.07R to 0.14R as the parameter drops from 0.7 to 0.3, while val/test stay pinned near 0.03-0.05R across the whole range, barely reacting at all. The neighbor-stability chart shows the same story from a different angle: the winner's train bar (0.136R) sits well above every neighbor's val/test bars, and two of the eight one-step neighbors (`min_risk=0.5`, `min_risk=0.7`) have outright *negative* validation expectancy while their train expectancy stays positive — a visually obvious sign the winner is not on a broad, robust plateau.

**What the plots show, EURUSD/choch_only (visualizes the unusual val/test > train pattern):** the same 4 panels show train, val, and test as three roughly parallel lines with val and test consistently *above* train at every single grid point tested, not just at the winner — this isn't an artifact of the specific winning combination, it holds across the whole one-at-a-time sweep. The `MAX_STOP_ATR_MULTIPLE` panel is the clearest: train stays flat around 0.11R across the whole range while test stays flat around 0.28-0.30R, a consistent ~0.17-0.19R gap in the "good" direction at every point. The neighbor-stability chart shows all 8 neighbors following the same ordering (test > val > train) with no crossovers — a stable, not cherry-picked, pattern for this symbol/mode on this window.

**Where it lives in code:** `scripts/backtest/plot_grid_sensitivity.py` (new), `requirements.txt` (`matplotlib>=3.8.0` added). Output: `docs/optimization_results/20260817_115757_sensitivity/` — 8 PNGs, 2 per symbol/mode combination.

**Status:** complete, all 4 combinations plotted and described.

---

## 5-part statistical rigor pass: negative control, random baseline, grid median, bootstrap CI + Cliff's delta, MCC

**What was added, in priority order (negative control checked and reported first, as instructed, before anything else proceeded):** `scripts/backtest/negative_control_temporal_shift.py` (-12h temporal shift, entry re-anchored, $ risk/reward preserved from the real trigger), `random_entry_baseline.py` (same design, 10 independent random-timestamp draws instead of one fixed shift), and `bootstrap_ci_and_mcc.py` (2000-resample bootstrap CI + Cliff's delta comparing the grid-search winner against production defaults over the full 200-day window, plus MCC). Grid-median-vs-defaults was computed directly from the existing grid CSVs, no new backtesting needed. Full results: `docs/optimization_results/20260817_rigor_checks_summary.md`/`.csv`.

**Item 1 (negative control) — clean, all 4 combinations, reported before anything else proceeded per the explicit priority instruction.** Every -12h-shifted version flipped to *negative* expectancy (e.g. XAUUSD choch_only: real +0.077R → shifted -0.103R) with win rate dropping 8-10 points — the opposite of what a lookahead bug would produce (a real bug wouldn't care which arbitrary shifted moment it's attached to). No evidence of lookahead bias.

**Item 2 (random-entry baseline) — clean, all 4 combinations.** Real expectancy exceeded every one of 10 independent random-timestamp draws in every combination (z-scores 2.90-8.47). Genuine information content beyond generic favorable drift.

**Item 3 (grid median) — defaults at-or-above median in 3 of 4 combinations**, essentially at median (46.9th percentile) in the 4th. Not a case where defaults are only defensible against a lucky top-of-grid outlier.

**Item 4 (bootstrap CI + Cliff's delta) — the humbling finding of this pass.** Despite the grid-search winner scoring higher point-estimate expectancy in all 4 combinations, Cliff's delta was negligible (<0.07) and the 95% expectancy CIs overlapped substantially in every single combination. **The grid search's apparent improvement over production defaults is not statistically distinguishable from noise at this sample size, over the full period** — consistent with, not contradicting, the overfitting signal already found and visualized for XAUUSD in the sensitivity-plots entry above. This tempers that entire prior optimization exercise: a higher-ranked combo on an 81-cell grid is not the same as a demonstrated real improvement.

**Item 5 (MCC) — confirms `backtest_trades` needs no schema change**, and adds a genuinely non-degenerate use of MCC: `matthews_corrcoef(direction_is_bullish, won)`, testing whether the edge is direction-dependent (relevant given gold's flagged one-directional bull-run regime — a naive "MCC of a single win/loss sequence against a constant predicted-win" would have been undefined, denominator zero). All 8 values (4 combinations × defaults/winner) were near zero (|MCC| < 0.08) — no meaningful concentration in the bullish direction despite the regime. Reassuring, not conclusion-changing.

**On "replace the old optimization results" — investigated before acting, found NOT superseded, so NOT deleted.** The user asked to delete the original grid-search CSVs/markdown/sensitivity-plot files and replace them with this rigor pass, but only after confirming they're genuinely superseded first. They are not: `bootstrap_ci_and_mcc.py` directly reads the original 4 grid CSVs (`20260817_11{1916,2645,3701,4512}_*_grid.csv`) to re-derive the "winner" parameters for comparison — deleting them would break this rigor pass's own reproducibility, not replace it with something equivalent. The 5-part rigor pass is a validation LAYER on top of the original grid search's output, not a re-run of the grid search itself with a different methodology. Original grid CSVs, markdown reports, and sensitivity PNGs are kept as-is; this rigor pass's own outputs are new, additional files alongside them, not replacements.

**Where it lives in code:** `scripts/backtest/negative_control_temporal_shift.py`, `random_entry_baseline.py`, `bootstrap_ci_and_mcc.py` (all new, exploratory only, write nothing back to any table). Output: `docs/optimization_results/20260817_rigor_checks_summary.md` + `.csv`.

**Status:** complete, all 5 checks run for all 4 combinations. No change to production defaults recommended. Original optimization-results files retained (confirmed not superseded, not deleted).

## Confluence Zone Engine: HTF multi-factor confluence clustering (replacing single-factor CHoCH-based zone reliance)

**What was built:** `analysis/strategies/confluence_zone_engine.py`, a new clustering/scoring layer on top of the existing `SMCZoneStateEngine` (FVG/OB/swing S/R), `SMCStructureEngine` (CHoCH), and `LiquiditySweepStateEngine` (BSL/SSL sweep) — reused unchanged, not reimplemented. It groups same-direction, price-overlapping factor events that fall within `CONFLUENCE_TIME_WINDOW_BARS=5` bars of the cluster's most recently added member into a single confluence zone, per the user's 6 explicit design decisions:

1. **Two selectable modes, not one chosen threshold** — `mode_a_2factor` (any 2 of 5 factor types) and `mode_b_3factor` (any 3 of 5), same pattern as `LTFTriggerEngine`'s `choch_only`/`choch_sweep`.
2. **Equal-weight factors, CHoCH not mandatory** — a zone built from FVG+OB alone has the same standing as one built from CHoCH+Sweep.
3. **Zone boundaries** — `zone_full_range` is the union of every contributing factor's price range; `zone_core_range` is the intersection of the RANGED factors only (OB/FVG/SwingSR — CHoCH/Sweep are point events and can't narrow an intersection), falling back to the full range when fewer than 2 ranged factors contributed.
4. **Lifecycle this pass** — `active` (default) or `invalidated` (price closed fully through `zone_full_range` on the adverse side, mirroring `zone_state.py`'s existing OB/FVG close-through rule). `won`/`lost` are reserved schema states for the follow-up LTF entry-finding pass, not set here.
5. **Confidence score = `factor_count` as `"X/5"`**, deliberately not a weighted/black-box formula, per the user's explicit interpretability request.
6. **`factors` JSON column stores the full per-factor breakdown** (type, own price range or point price, formation bar) so the dashboard's planned "show all contributing factors" panel extension needs no future schema change.

**"CRT sweep" disambiguation (not specified by the user, a real design choice):** mapped to `LiquiditySweepStateEngine`'s BSL/SSL detection, not `CRTStateEngine`'s Asian-session sweep — the latter is an h1-specific session concept that doesn't generalize to h4/h6/d1.

**Schema:** new `confluence_zones` table added to `storage/schema_curated.sql` for both `curated_gold`/`curated_eurusd` (mirrors `smc_signals`'s structure/index conventions) and created live in both databases. `UNIQUE KEY uq_zone (symbol, timeframe, mode, direction, created_at_bar)` — re-running detection upserts, doesn't duplicate.

**Detection script:** `scripts/detection/run_confluence_zone_detection.py` — resamples the rolling-730-day h1 window to h4/h6/d1 (same `resample_ohlc()` used by every other HTF consumer), runs both modes, upserts.

**Unit tests:** `tests/test_confluence_zone_engine.py`, 6 hand-constructed scenarios matching the `test_smc_zone_state.py` style (helper builder, plain asserts, `python tests/test_X.py` runnable) — clustering merge/no-merge on direction and time window, core-range intersection with point-event exclusion and the <2-ranged-factor fallback, a real OB+FVG+SwingSR+Sweep bullish reversal sequence qualifying under mode_a, mode_b correctly rejecting a weaker cluster mode_a accepts, and adverse close-through invalidation. All 6 pass against the real engines (not mocked).

**Real-data validation (XAUUSD, 726-day rolling window, all 3 HTF timeframes, both modes):**

| timeframe | mode_a_2factor zones | mode_a zones/day | mode_b_3factor zones | mode_b zones/day |
|---|---|---|---|---|
| h4 | 350 | 0.48 | 144 | 0.20 |
| h6 | 234 | 0.32 | 98 | 0.13 |
| d1 | 78 | 0.11 | 24 | 0.03 |

Factor-count distribution skews toward the minimum threshold at both modes (e.g. h4 mode_a: 206 zones at 2 factors, 114 at 3, 28 at 4, 2 at 5-factor "perfect" confluence) — consistent with the design-options survey's real-data findings from earlier this session, and still below the user's originally stated "4-5 zones/day" expectation at every timeframe/mode combination, same gap flagged during the design-options phase and not resolved by this implementation (out of scope — the design decisions explicitly fixed the clustering rule, not the target zone rate).

**Observed clustering behavior worth flagging:** because the time window is measured from each cluster's *most recently added* member (not its first), a chain of factors arriving every few bars can let a single cluster span multiple days even though no two adjacent factors are more than 5 bars apart — e.g. one real h4 bearish 5/5-confidence zone spans 2026-02-08 20:00 to 2026-02-12 20:00 (4 days) via a chain of swing/sweep/OB/CHoCH/FVG factors each within the 5-bar window of the previous one. This is the same chain-clustering algorithm validated against real data during the design-options survey (not a new bug introduced here), but is worth the user's awareness when cross-checking wide zones against a chart.

**Where it lives:** `analysis/strategies/confluence_zone_engine.py`, `scripts/detection/run_confluence_zone_detection.py`, `tests/test_confluence_zone_engine.py`, `storage/schema_curated.sql` (`confluence_zones` table, both databases).

**Status:** HTF confluence layer complete and validated for XAUUSD across h4/h6/d1, both modes. EURUSD detection run and dashboard integration not yet done this pass. LTF (m5/m15) entry-finding within these zones and the dashboard panel extension are explicitly deferred to a follow-up pass, per the user's instruction.

## Confluence Zone Engine: dual-bound clustering (span cap added on top of the gap-based window)

**Problem found (flagged by the user after reviewing a real example from the previous entry):** `_cluster_events()`'s gap check resets `last_ts` on every new member it accepts, so a chain of factors arriving no more than `CONFLUENCE_TIME_WINDOW_BARS` apart can extend a cluster indefinitely — the real XAUUSD h4 zone flagged earlier (2026-02-08 20:00 → 2026-02-12 20:00) spanned 96 hours via 14 factors each individually within the 20h gap window of the previous one.

**Fix implemented:** a second, independent bound, `CONFLUENCE_MAX_SPAN_BARS`, measured from the cluster's `first_ts` (not the rolling `last_ts`). A candidate factor now joins an existing cluster only if it satisfies BOTH the gap check (`<= CONFLUENCE_TIME_WINDOW_BARS` from the last member) AND the span check (`<= CONFLUENCE_MAX_SPAN_BARS` from the first member); failing either starts a new cluster. `analysis/strategies/confluence_zone_engine.py`: `_cluster_events()` now takes a `span_delta` parameter, `detect_confluence_zones()` computes it from the new constant the same way `bar_delta` is computed.

**Value chosen empirically, not guessed — tested 10/15/20-bar candidates (40h/60h/80h at h4) against the real 726-day XAUUSD dataset already used for validation:**

| cap (bars) | h4 hours | qualifying 2+ | qualifying 3+ | baseline multi-member clusters split |
|---|---|---|---|---|
| none (baseline) | — | 350 | 144 | — |
| 10 | 40h | 379 | 139 | 48 of 400 (12%) |
| 15 | 60h | 361 | 142 | 20 of 400 (5%) |
| 20 | 80h | 354 | 145 | 10 of 400 (2.5%) |

Baseline max multi-member cluster span was 116h; qualifying(3+) counts stay close to baseline at every candidate (139-145 vs 144), so none of the three candidates meaningfully changes how many real confluence zones get reported — the cap mainly reshapes a small number of long-tail clusters, not the overall detection rate.

**Chose 15 bars (60h at h4).** Spot-checked 3 of the 20 clusters that split under this cap (`docs/DECISIONS.md` history / session transcript has the full breakdown): in every case, the split cleanly separated a genuine multi-factor structural cluster (which kept its full factor set and stayed qualifying) from a short trailing tail of 1-2 further single-factor events spaced further out — those tail pieces never reach `factor_count >= 2` on their own and simply stop being reported as confluence zones, rather than fragmenting one real zone into two competing qualifying zones. 10 bars split more clusters (48 vs 20) for essentially the same qualifying-count outcome, and 20 bars barely capped anything relative to the 116h baseline max — 15 bars was the point where the cap was doing real work without being aggressive. Verified the same relationship holds at h6 (max baseline span 120h, capped-15 barely changes qualifying counts: 234→237 at 2+, 98→98 at 3+) and d1 (max baseline span 456h/19 days, capped-15 234→79 at 2+ — negligible change) — the bar-count-based cap scales the same way `CONFLUENCE_TIME_WINDOW_BARS` was designed to.

**Flagged as an unvalidated starting point in the module docstring/constant comment**, same convention as `STRUCTURAL_TP_FRACTION`/`CONFIRMATION_WINDOW_BARS`/`SMC_ZONE_RECENCY_WINDOW_BARS` — validated against one real symbol's data at one point in time, not swept/optimized against a held-out period.

**Re-validated on real data with the cap applied (XAUUSD, all 3 timeframes, both modes, re-detected from scratch after clearing the pre-cap rows):**

| timeframe | mode_a_2factor zones | mode_a zones/day | mode_b_3factor zones | mode_b zones/day | max cluster span |
|---|---|---|---|---|---|
| h4 | 361 | 0.50 | 142 | 0.20 | 60h (= cap) |
| h6 | 237 | 0.33 | 98 | 0.13 | 90h (= cap) |
| d1 | 79 | 0.11 | 24 | 0.03 | 336h (under the 360h cap) |

The originally flagged h4 zone (2026-02-08 20:00 → 2026-02-12 20:00, 5/5 confidence) now correctly splits into two pieces: an initial 2-factor piece (2026-02-08 20:00 → 2026-02-11 08:00, 60h, no longer qualifies mode_b) and the strong tail piece (2026-02-11 12:00 → 2026-02-12 20:00, 32h, still 5/5 confidence, qualifies both modes) — confirmed directly against the live table.

**Unit test added:** `test_span_cap_splits_a_long_chain_even_when_every_gap_is_tight` in `tests/test_confluence_zone_engine.py` — a synthetic chain of same-direction, overlapping-price events spaced well inside the gap window but long enough in total to exceed `CONFLUENCE_MAX_SPAN_BARS`, asserting it stays as one cluster with no span cap and splits into 2+ (each individually within the cap) with it. All 7 unit tests pass.

**Status:** dual-bound clustering complete and validated. This closes the HTF Confluence Zone Engine implementation pass. LTF (m5/m15) entry-finding within these zones is next.
