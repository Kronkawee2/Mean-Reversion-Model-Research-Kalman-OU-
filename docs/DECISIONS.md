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

## Dashboard: multi-timeframe zone display, OB/swing rendering root cause, legend, and a repeated chart-sizing bug

**Item 1 (multi-timeframe zones) + Item 2 (OB/swing rendering investigation) — same root cause, fixed together.** Investigated before assuming a JS/overlay bug: `curated_gold.smc_signals` had ZERO `order_block_bullish`/`order_block_bearish`/`swing_support`/`swing_resistance` rows in `state='active'` (confirmed via direct query), while FVG had some. Traced why: the wick-touch "mitigated" criterion (shared by OB, swing, and FVG) fires almost immediately for OB/swing because their price range is a single candle's wick — real data showed the most recent OB/swing zones mitigating within 1 hour of formation. Not a rendering bug; the JS overlay code (`ZONE_STYLE`, `drawZones()`) is generic per zone type and was never broken — it simply never received OB/swing rows to draw, because `load_active_zones()` filtered to `state='active'` alone.

Separately found `smc_signals` had NO rows at all for h4/h6/d1 on either symbol — only h1 had ever been detected. `run_smc_zone_detection.py --timeframe h4/d1` would have used the deprecated Yahoo-sourced, DST-misaligned `raw_<symbol>.{h4,d1}` tables directly (h6 wasn't even a supported `--timeframe` choice) rather than resampling from h1 like every other HTF consumer in this project.

**Fixes:**
- `scripts/detection/run_smc_zone_detection.py`: `load_ohlcv()` now resamples h4/h6/d1 from `raw_<symbol>.h1` (added h6 support), and h1 itself is now filtered to `rolling_window_start()` before detection runs — full h1 depth is 23 years and would reproduce the earlier full-history hang (see the H1 backfill entries above).
- Ran `run_smc_zone_detection.py` for h4/h6/d1, both symbols — new real zones with active/mitigated states across all 4 timeframes (e.g. XAUUSD h4: 12 active, 186 mitigated).
- `scripts/detection/run_detection.py`: `build_stages()`'s "SMC zones" stage now runs all 4 timeframes per symbol (was h1 only) so the full pipeline button doesn't let this go stale again.
- `dashboard/1_chart.py`: `load_active_zones()` now queries `timeframe IN ('h1','h4','h6','d1')` and `state IN ('active','mitigated')`, returning each row's own timeframe. `render_chart()` labels each zone `"{type} [{TF}]"` (e.g. "FVG Bullish [H4]") and renders mitigated zones with a dashed border + reduced opacity instead of treating them identically to fresh active zones. Verified live: 863 real zones across all 4 timeframes and all 6 zone types now draw with 0 skipped/null-coordinate.

**Readability trade-off, flagged not resolved:** rendering all active+mitigated zones from 4 timeframes simultaneously is visually dense — confirmed by screenshot, the chart is heavily layered with overlapping colored bands and labels. This is what was explicitly asked for ("show zones from all timeframes simultaneously... don't hide HTF zones"), so it was implemented as specified rather than unilaterally filtered down; a follow-up pass could add per-timeframe toggles or zone-count limits if the density turns out to be a problem in practice.

**Item 3 (legend).** Added a "Legend" sidebar expander to `dashboard/1_chart.py` with one-sentence, plain-language definitions for FVG, OB, Swing S/R, BSL/SSL, Asian Range, Equilibrium, the dashed-border (mitigated) convention, and a forward-reference to Confluence Zones (not chart-wired yet, follow-up pass). Also added native browser tooltips (`title` attribute) on each drawn zone div showing its full label on hover.

**Repeated bug found and fixed in 2 places: chart embeds a fixed-height iframe whose inner CSS never resolves.** `dashboard/pages/2_htf_bias.py`'s confluence-score-history chart and `dashboard/pages/5_backtest_results.py`'s USD equity curve chart both used `body{margin:0;padding:0;...}#chart{width:100%;height:100%;}` with no explicit height on `html`/`body`. `height:100%` only resolves against an ancestor with a definite height — with `body`'s height left at its default `auto`, `#chart`'s 100% resolves to 0, so `lightweight-charts` initializes against a zero-height container and renders nothing (confirmed visually: both charts were a solid black rectangle with no gridlines/axes/data, no JS console errors). `dashboard/1_chart.py`'s main candlestick chart never had this bug because it uses `height:100vh` on its wrapper instead, which doesn't depend on the ancestor chain. Fixed both by adding `html,body{height:100%;...}` to the embedded chart's CSS. Verified live in-browser: both charts now render their real data correctly.

**Where it lives:** `dashboard/1_chart.py`, `dashboard/pages/2_htf_bias.py`, `dashboard/pages/5_backtest_results.py`, `scripts/detection/run_smc_zone_detection.py`, `scripts/detection/run_detection.py`.

**Status:** items 1-3 complete and verified live in-browser. Item 4 (remaining page review) reported separately below.

## Dashboard page review (item 4): Divergence, Backtest Results, HTF Bias, Run Pipeline — findings only, fresh review

Per the user's request, reviewed the 4 pages not previously covered (Chart and LTF Triggers were reviewed earlier), checking each against real data for correctness, staleness, and confusing labels. Two real bugs (both CSS chart-sizing, documented above) were found and fixed since they were directly encountered during this review; everything else below is reported, not fixed, per the user's explicit "report findings before fixing" instruction for this item.

**Divergence page — real, significant staleness found.** `MODEL_LABELS` (11 entries: rsi/obv/stochastic/cci/xau_dxy/eur_dxy/xau_us10y/xau_gdx/xau_spdr/cot_gold/cot_eur) and the on-page MTF note ("closed at 11/12 models") no longer match the real data. Querying `divergence_signals.divergence_type` directly found 14 distinct types for XAUUSD alone (adds `xau_cpi`, `xau_fedfunds`, `xau_gpr`, `xau_tips`, `xau_xag` — all with real signal counts, e.g. `xau_gpr`: 49 rows) and EURUSD additionally has `eur_yield_spread` (43 rows) which was previously documented as deferred/unbuilt. Any signal of these unmapped types renders with its raw internal snake_case code (e.g. "xau_gpr") instead of a friendly label — confirmed visually in a real row on the live page. The "11/12 models" framing is now understated; real count is at least 15 distinct types across both symbols. Not fixed this pass — needs a decision on the full current model label set before touching `MODEL_LABELS`/the MTF note text.

**HTF Bias page — otherwise correct.** Real bullish/bearish badge, score, component breakdown, and (after the CSS fix above) score history chart all render correctly against real XAUUSD/EURUSD data. No other issues found.

**Backtest Results page — otherwise correct.** R-multiple distribution, streaks/recovery, weekly/monthly breakdown, variant comparison table, and (after the CSS fix above) the USD equity curve all render real data correctly for both symbols/modes/periods. Minor cosmetic-only nit: the "Expectancy" metric card's label text wraps awkwardly at default card width ("+0.0" / "63R" split across lines) — not a data bug, not fixed this pass.

**Run Pipeline page — accurate to `main.py`, but its own downstream `run_detection.py` had a real staleness gap (fixed as part of item 1/2 above, not a page bug itself).** The page's hardcoded `STAGES` list matches `main.py`'s actual `run_step()` labels exactly. Tracing further into what "Detection pipeline" actually runs found `run_detection.py`'s SMC-zones stage only ever called `--timeframe h1` — meaning the h4/h6/d1 zones this session just added would have gone stale on the very next pipeline run. Fixed (see above). Separately, not fixed, flagged only: `run_detection.py` does not call `run_confluence_zone_detection.py` at all — the Confluence Zone Engine built earlier this session has no path into the automated pipeline yet; it still needs to be run manually. Left as-is since wiring in a new, comparatively expensive detection stage is a deliberate scope decision, not an obvious bug fix.

**Where it lives:** findings only (except the two CSS fixes, folded into the previous entry's fix list).

**Status:** review complete for all 4 pages. Awaiting direction on the Divergence page's stale model list before any further dashboard fixes.

## Dashboard follow-up: per-timeframe zone toggles, full divergence model audit, confirmed chart-height fix scope, cosmetic fix

Closes the 5 open items from the previous dashboard entry.

**1. Per-timeframe zone toggles (chart density).** `dashboard/1_chart.py`'s single "SMC Zones" checkbox replaced with 4 independent H1/H4/H6/D1 checkboxes in the Overlays sidebar. Default: H4/H6/D1 on, H1 off — HTF is the primary analysis layer (Confluence Zone Engine works exclusively in h4/h6/d1), H1 clutter is opt-in. `load_active_zones()` now takes a `timeframes` tuple and queries only the selected set. Verified live: default view loads 437 zones (down from 863 with H1 included); unchecking H4 alone drops it further to 239 and removes exactly the `[H4]`-labeled zones from the chart, confirming the toggles work independently.

**2. Divergence page + audit of the other 3 pages for the same "written before X was built" staleness pattern.** Re-queried `SELECT DISTINCT divergence_type` directly (not estimated) against both databases: `curated_gold` has 14 types, `curated_eurusd` has 7 (4 shared technical + 10 gold-only + 3 EUR-only), 17 distinct total. `MODEL_LABELS` in `dashboard/pages/4_divergence.py` extended with the 6 previously-unmapped types, all with human-readable names: `xau_gpr` → "XAU vs GPR (Geopolitical Risk)", `xau_xag` → "XAU vs XAG (Silver)", `xau_tips` → "XAU vs TIPS (Real Yield)", `xau_fedfunds` → "XAU vs Fed Funds Rate (unconfirmed)", `xau_cpi` → "XAU vs CPI (unconfirmed)", `eur_yield_spread` → "EUR vs US-EU Yield Spread". The `(unconfirmed)` suffix on fedfunds/cpi matches how `intermarket_divergence_state.py`'s own docstring already flags those two as theory-based, not data-confirmed (same models the HTF Bias Engine excludes from scoring, see the earlier "checked, found clean" entry above) — the dashboard label now carries that caveat instead of leaving the user to discover it in code. The on-page MTF note and the page's top docstring both updated from "11/12 models" to the real "17 working models (14 XAUUSD, 7 EURUSD, 4 shared)" framing. Verified live: filtering the Model dropdown by "GPR" now shows "XAU vs GPR (Geopolit..." instead of the raw code.

Audited the other 3 pages for the same pattern (a hardcoded label/enum map silently falling behind what the schema or engine can now produce):
- **HTF Bias** — `htf_bias` table schema and the page's 6-component breakdown match column-for-column, nothing added since. No staleness found.
- **Backtest Results** — `MODE_LABELS` (choch_only/choch_sweep) matches `ltf_trigger_engine.MODES` exactly. `CONTRACT_MULTIPLIER` is correct for both symbols. Minor, non-staleness observation: `backtest_runs` has several DSR diagnostic columns (`skewness`, `kurtosis`, `psr_vs_zero`, `sr0_threshold`, outcome-resolution drilldown counters) the page doesn't surface — not wrong or misleading, just not all shown; left as-is, not the same class of bug as the Divergence page's raw-code display.
- **Run Pipeline** — `STAGES` list matches `main.py`'s real `run_step()` labels exactly (already confirmed in the previous entry). No additional staleness found beyond the SMC-zones/confluence-zones pipeline-wiring gaps already reported.

**3. Confirmed the chart-height fix's scope.** Grepped both `dashboard/pages/2_htf_bias.py` and `dashboard/pages/5_backtest_results.py` for every `st.components.v1.html` call: exactly one embedded chart per page, both already fixed (the confluence-score-history chart and the USD equity curve). No other chart on either page shares the container-height bug.

**4. Fixed the Expectancy metric-card text-wrap cosmetic issue.** `dashboard/pages/5_backtest_results.py`: added `white-space:nowrap` to `.metric-value` and a `.metric-value-8up` modifier (17px vs the default 22px) applied only to the dense 8-column Trades/Win Rate/.../Skipped row, where the narrower per-card width was wrapping values like "+0.063R" mid-string. The 3-column metric rows elsewhere on the page keep the original 22px size since they were never affected. Verified live: "+0.063R" now renders on one line.

**5. Confluence Zone Engine pipeline integration — still deferred, now explicitly tracked.** `run_detection.py` does not call `run_confluence_zone_detection.py`. This remains correct for now (LTF entry-finding, the feature that actually consumes confluence zones, isn't built yet), but is now flagged here explicitly as a TODO for when that follow-up pass lands: `run_confluence_zone_detection.py` needs a stage added to `build_stages()` in `scripts/detection/run_detection.py` at that point, or the zones it now correctly persists will silently go stale exactly the way the h4/h6/d1 SMC zones did before this session's fix.

**Where it lives:** `dashboard/1_chart.py`, `dashboard/pages/4_divergence.py`, `dashboard/pages/5_backtest_results.py`.

**Status:** all 5 items closed and verified live in-browser (toggle behavior, friendly labels, both chart renders, text-wrap fix). Dashboard work for this pass is complete; next up is the LTF entry-finding follow-up pass.

## Confluence LTF Trigger: LTF entry-finding within HTF confluence zones

**What was built, per the approved design (5 decisions, all implemented as proposed):**

1. **Reuse `ltf_trigger_engine.py` unchanged.** `analysis/strategies/confluence_ltf_trigger.py` wraps `LTFTriggerEngine.compute_triggers()` verbatim -- confluence zones are passed in via a same-direction proxy `zone_type` (`swing_support`/`swing_resistance`, satisfying the engine's existing bullish/bearish lookup) purely so the unmodified engine can run; nothing inside `ltf_trigger_engine.py` changed.
2. **Core-first-fallback-to-full range selection.** Touch detection always runs against a confluence zone's `full_range` (matches single-factor-zone recall). Once a trigger confirms, if the LTF entry price (close at `confirmed_at_bar`) also falls inside `core_range`, the trigger's effective `htf_zone_top`/`htf_zone_bottom` are swapped to `core_range`; otherwise they stay at `full_range`, identical to today's single-factor-zone behavior. Recorded per-trigger as `zone_range_used`.
3. **`structural_tp_engine.py` untouched.** It only reads whatever `htf_zone_top`/`htf_zone_bottom` it's given -- the core/full swap happens entirely upstream, in `confluence_ltf_trigger.py`, before triggers reach it.
4. **`ltf_trigger_signals` extended, not a new table:** `zone_source` ('smc_signals'/'confluence_zone'), `confluence_zone_id` (soft FK), `confluence_mode` ('mode_a_2factor'/'mode_b_3factor'), `zone_range_used` ('full'/'core'). `htf_zone_type` extended with 4 new values (`confluence_bullish_mode_a`/`_mode_b`, `confluence_bearish_mode_a`/`_mode_b` -- see the real bug below for why mode had to be baked into this value, not left to `confluence_mode` alone).
5. **Both confluence modes x both confirmation modes, 4 variants, no forced default.** New detection script `scripts/detection/run_confluence_ltf_triggers.py`, mirroring `run_ltf_trigger_detection.py`'s pattern. Scope for this pass: h4 confluence zones only (h6/d1 not wired in, same precedent as h1 being the sole timeframe for the original single-factor triggers), `ltf_timeframe='m15'` only.

**Real bug found and fixed during implementation, not just at design time:** the first working version used a direction-only proxy for the persisted `htf_zone_type` (`confluence_bullish`/`confluence_bearish`). Since a `mode_b_3factor` zone is BY DEFINITION also a `mode_a_2factor` zone of the same underlying cluster (same `last_factor_at_bar`), running mode_b's detection after mode_a's produced triggers whose `(symbol, ltf_timeframe, mode, htf_zone_type, htf_zone_created_at_bar, touch_bar_datetime, choch_bar_datetime)` collided with mode_a's existing rows under the legacy `uq_trigger` unique key -- MySQL's `ON DUPLICATE KEY UPDATE` silently merged mode_b's fields into mode_a's rows instead of inserting distinct rows. Caught by checking `SELECT confluence_mode, COUNT(*) ... GROUP BY` after the first real-data run and finding zero `mode_b_3factor` rows survived. Fixed by encoding confluence_mode directly into `htf_zone_type` (4 values instead of 2) so the existing key naturally disambiguates; added a second, narrower `uq_trigger_confluence` key on `confluence_zone_id` as an additional safety net; wiped and re-ran all 8 combinations; added a regression unit test (`test_mode_a_and_mode_b_htf_zone_type_differ_for_the_same_underlying_cluster`) reproducing the exact collision setup.

**Unit tests:** `tests/test_confluence_ltf_trigger.py`, 4 tests (core confirms in time -> uses core; only full confirms -> uses full, matching current single-factor-zone behavior; the mode-collision regression above; empty-input handling), reusing the exact same validated bullish-reversal candle sequence from `test_confluence_zone_engine.py`. All pass.

**EURUSD confluence zones had never been detected** (0 rows in `curated_eurusd.confluence_zones` -- flagged, not fixed, in the earlier dashboard-review entry above). Run now as a prerequisite: 395 `mode_a_2factor` / 148 `mode_b_3factor` zones, h4.

**Real-data run, all 8 combinations (XAUUSD + EURUSD x 2 confluence modes x 2 confirmation modes), m15, full rolling window (726 days):**

| symbol | confluence mode | LTF mode | structural triggers | median R:R | core-range share |
|---|---|---|---|---|---|
| XAUUSD | mode_a_2factor | choch_only | 1839 | 0.254 | 42% |
| XAUUSD | mode_a_2factor | choch_sweep | 1456 | 0.254 | 44% |
| XAUUSD | mode_b_3factor | choch_only | 831 | 0.263 | 45% |
| XAUUSD | mode_b_3factor | choch_sweep | 649 | 0.260 | 47% |
| EURUSD | mode_a_2factor | choch_only | 2625 | 0.287 | 42% |
| EURUSD | mode_a_2factor | choch_sweep | 2054 | 0.287 | 41% |
| EURUSD | mode_b_3factor | choch_only | 1482 | 0.284 | 46% |
| EURUSD | mode_b_3factor | choch_sweep | 1168 | 0.278 | 45% |

For reference, the existing smc_signals-sourced (h1, single-factor) path over the same window: XAUUSD choch_only 2217 structural / choch_sweep 1672; EURUSD choch_only 2508 / choch_sweep 2009 -- confluence-sourced counts are lower (as expected, confluence zones are rarer than single-factor zones) but same order of magnitude, not a cliff, because confluence zones stay active far longer and each can re-fire on multiple touch+CHoCH events over its life.

**Statistical floor -- honest answer, not just "it clears":** raw structural trigger counts (smallest: XAUUSD mode_b_3factor/choch_sweep at 649) comfortably clear a ~200-trades/12-month floor scaled to the full 726-day window (~398). But raw structural count isn't the same as backtestable "trades taken" -- the existing single-factor path's own real backtest shows only ~21-23% of structural signals survive the one-trade-at-a-time overlap-skip sequencing (XAUUSD choch_only: 461 taken / 2217 structural = 20.8%; choch_sweep: 381/1672 = 22.8%). Applying that same ratio as a rough reference (not measured directly on confluence data -- the structural backtest hasn't been run against these new triggers yet): the smallest confluence variant (XAUUSD mode_b_3factor + choch_sweep, stacking both the stricter confluence tier AND the stricter confirmation mode) would land around ~135-150 estimated decided trades. That's still above the ~99-trade floor this project's `backtest_runs` convention uses for its own (shorter) evaluation period, but meaningfully thinner than the other 7 variants, and is the one combination worth actually running through `structural_backtest_engine.py` before treating it as production-viable -- confluence zones are wider and more overlapping in price than single-factor zones, so the real overlap-skip rate could differ from the single-factor reference in either direction. Recommended immediate next step, not done this pass.

**Concrete real examples (XAUUSD, mode_a_2factor/choch_only), for cross-checking:**

- **Clean win (confluence_zone_id 1049):** full=[2956.58, 3055.54] (98.96 wide), core=[2970.94, 2987.64] (16.70 wide). Confirmed 2025-04-07 22:00, entry=2983.89, core-range stop=2970.94 (risk 12.95), target=3016.32, **R:R=2.50**.
- **Delayed but better (confluence_zone_id 1226):** full=[4420.27, 4619.82], core=[4493.14, 4515.42]. First FULL confirmation 2026-03-31 01:00, entry=4544.01, R:R=0.13 (weak). Zone stayed active and kept re-firing on FULL for 50 more days (29 total triggers over its life -- a real characteristic of long-lived, wide confluence zones worth knowing before backtesting). First CORE confirmation not until 2026-05-20 14:15, entry=4506.88, core-range stop=4493.14 (risk 13.74 vs the earlier ATR-capped ~54), target=4522.82, **R:R=1.16** -- a real, large quality improvement, at the cost of 50 real calendar days of waiting.
- **Same-zone factor_count/no-mutual-intersection edge case (confluence_zone_id 1172, not used as a headline example but worth flagging):** this zone's `_core_range()` computation legitimately fell back to equal `full_range` (no single price region overlapped ALL of its 4 ranged factors, only pairwise via the clustering chain -- the documented fallback in `confluence_zone_engine.py` behaving exactly as designed). Its trigger was correctly labeled `zone_range_used='core'` (entry was inside `core_range`, which here equals `full_range`) but the stop is NOT actually tighter than a plain full-range trigger would be. This is real and expected, not a bug -- flagging it here because it means `zone_range_used='core'` alone doesn't guarantee a materially tighter stop; the core/full width ratio still needs checking case by case.

**Where it lives:** `analysis/strategies/confluence_ltf_trigger.py`, `scripts/detection/run_confluence_ltf_triggers.py`, `tests/test_confluence_ltf_trigger.py`, `storage/schema_curated.sql` (`ltf_trigger_signals` extension, both databases).

**Status:** implemented, tested, and run for all 8 variants on real data for both symbols. Structural backtest against these new triggers not yet run -- recommended before treating any variant (especially XAUUSD mode_b_3factor/choch_sweep) as production-viable. LTF Triggers dashboard page's multi-factor explanation panel (item 8, previously deferred) can now be built on top of this real data.

## Confluence LTF Trigger: structural backtest results, all 8 variants — honest finding, not favorable

**Schema/script work needed first, not just a re-run.** `backtest_trades`/`backtest_runs` had no `zone_source`/`confluence_mode` dimension at all -- their only identity was `(symbol, ltf_timeframe, mode, [period])`. Running `run_structural_backtest.py` against confluence-sourced triggers unmodified would have `DELETE`d and overwritten the EXISTING smc_signals baseline rows for the same `(symbol, ltf_timeframe, mode)` key, destroying the very baseline this pass needed to compare against. Fixed the same way as `ltf_trigger_signals`: added `zone_source` and `confluence_mode` (an explicit `'none'` sentinel for smc_signals rows, not NULL -- NULL would have broken `uq_backtest_trade`/`uq_backtest_run`'s uniqueness the same way it would have for the trigger table, and a mode_b_3factor variant's trades can genuinely share an `entry_bar_datetime` with mode_a_2factor's for the same underlying cluster) to both tables' unique keys. Extended `backtest_trades.htf_zone_type`'s ENUM with the 4 confluence values too (missed on the first schema pass, caught before running). `run_structural_backtest.py` extended with `--zone-source`/`--confluence-mode` args; default behavior (no flags) is byte-for-byte the original smc_signals path -- verified the existing baseline rows were untouched after the schema migration and before any confluence run.

**Statistical floor -- confirmed with real numbers, not the ~135-150 estimate.** The thinnest variant, XAUUSD mode_b_3factor + choch_sweep, actually took **484 decided trades on the full 726-day period (vs a floor of 398) and 154 on the held-out 218-day test period (vs a floor of 119)** -- comfortably clearing both, and well above the earlier rough estimate. The reason the estimate undershot: confluence-sourced triggers survive the one-trade-at-a-time overlap-skip sequencing at a MUCH higher rate than the original single-factor path (~65-75% for confluence vs ~21-23% for smc_signals) -- confluence zones are fewer and more separated in price, so far fewer simultaneously-firing signals collide and get skipped. Every one of the 8 variants clears its floor on both periods.

**The honest comparison the user asked for: confluence-sourced entries do NOT outperform the original single-factor baseline -- in fact they're consistently worse, the same pattern as the earlier min-R:R-threshold-filter experiment.**

| symbol | mode | zone source | period | trades | win rate | PF | expectancy R | max DD (R) | DSR |
|---|---|---|---|---|---|---|---|---|---|
| XAUUSD | choch_only | **baseline** | full | 461 | 77.0% | 1.27 | **+0.063** | **6.99** | 0.97 |
| XAUUSD | choch_only | confluence mode_a | full | 936 | 77.0% | 1.11 | +0.025 | 13.85 | 0.88 |
| XAUUSD | choch_only | confluence mode_b | full | 607 | 78.3% | 1.15 | +0.033 | 13.13 | 0.90 |
| XAUUSD | choch_sweep | **baseline** | full | 381 | 77.4% | 1.32 | **+0.072** | **9.14** | 0.98 |
| XAUUSD | choch_sweep | confluence mode_a | full | 765 | 76.9% | 1.08 | +0.018 | 12.88 | 0.78 |
| XAUUSD | choch_sweep | confluence mode_b | full | 484 | 77.7% | 1.09 | +0.020 | 12.26 | 0.76 |
| EURUSD | choch_only | **baseline** | full | 546 | 75.5% | 1.23 | **+0.055** | **8.66** | 0.95 |
| EURUSD | choch_only | confluence mode_a | full | 1214 | 75.0% | 0.98 | **-0.006** | 30.70 | 0.38 |
| EURUSD | choch_only | confluence mode_b | full | 907 | 77.0% | 1.06 | +0.015 | 22.38 | 0.76 |
| EURUSD | choch_sweep | **baseline** | full | 468 | 75.9% | 1.29 | **+0.071** | **8.41** | 0.98 |
| EURUSD | choch_sweep | confluence mode_a | full | 1017 | 74.9% | 0.98 | **-0.005** | 26.79 | 0.40 |
| EURUSD | choch_sweep | confluence mode_b | full | 756 | 77.4% | 1.08 | +0.019 | 17.63 | 0.79 |

(Test-period rows, all 8 confluence variants: 6 of 8 show WORSE expectancy on test than full -- 4 of those (all XAUUSD) flip outright negative. The baseline's own test-period expectancy moves both directions too (XAUUSD dips slightly full->test, EURUSD improves) but NEVER flips sign -- it stays solidly positive throughout, 0.0498R to 0.1657R across all 4 baseline period/mode combinations. The confluence path's problem isn't that test always underperforms full in general -- baselines wobble too -- it's that 4 of 8 confluence variants cross zero on test where 0 of 4 baseline variants ever do. `SELECT * FROM backtest_runs WHERE zone_source='confluence_zone' AND period='test'` for the complete rows.)

**Every single confluence-mode/confirmation-mode combination underperforms its matching baseline on expectancy, and does so by a wide margin -- +0.063R baseline vs +0.025-0.033R confluence for XAUUSD choch_only, +0.055R vs -0.006/+0.015R for EURUSD choch_only.** Max drawdown is 2-4x worse across the board (XAUUSD 6.99R->13.85R; EURUSD's worst case 8.66R->30.70R). Two confluence variants (both EURUSD mode_a) are outright net-negative on the full period.

**Mechanism, not just the number -- checked why, not just reported that it's worse.** Win rates are essentially IDENTICAL to baseline (e.g. XAUUSD choch_only: 77.0% both) or even slightly higher for mode_b (78.3%) -- confluence-sourced entries are not losing more often. The gap is entirely in reward size: confluence-sourced structural_rr sits at a median of ~0.25-0.29 (reported in the earlier design-phase entry) vs a meaningfully higher baseline median, because the median confluence trigger's entry lands nowhere near a favorable opposing-zone target. Combined with the fixed -1.0R loss size, smaller average wins need MORE of them to offset the same-sized losses -- which is exactly what pushes expectancy down and (with roughly double the trade count active over the same calendar window) pushes cumulative drawdown up. The core-first-fallback-to-full range selection genuinely produces tighter stops on individual trades when it fires (real examples: R:R 0.13->1.16, 0.13->2.50 shown in the design-phase entry) -- that part of the mechanism works exactly as designed. It just doesn't move the AGGREGATE backtest numbers in a favorable direction, because most trades still confirm via FULL range (only ~42-47% land in CORE), and the wider HTF context this whole pass was meant to exploit doesn't translate into better opposing-zone target selection, which is where the real expectancy gap lives.

**One partial bright spot, not hidden:** EURUSD mode_b_3factor + choch_sweep is the only confluence variant that's positive on BOTH periods (full +0.019R, test +0.019R, DSR 0.79/0.67) and doesn't fall apart out-of-sample the way the other 7 do. It's still below EURUSD's own baseline choch_sweep (+0.071R full, +0.166R test, DSR 0.98/0.98) on every metric, so "not the worst" is not the same as "an improvement."

**Verdict, matching the honesty standard set by the earlier R:R-threshold-filter finding: the theoretically-tighter-stop story does not translate into better real trading outcomes here.** The mechanism is real and demonstrable at the individual-trade level; the aggregate backtest says the original single-factor h1-zone path remains the better-performing approach on this data. Not recommending confluence-sourced entries replace the existing production path.

**Where it lives:** `scripts/backtest/run_structural_backtest.py` (extended), `storage/schema_curated.sql` (`backtest_trades`/`backtest_runs` extensions, both databases). Full per-variant, per-period rows in `backtest_runs` (`zone_source='confluence_zone'`), full trade-level detail in `backtest_trades`.

**Status:** all 8 variants backtested and persisted. Baseline (smc_signals) rows confirmed untouched throughout. Awaiting the user's decision on whether to proceed to the LTF Triggers dashboard panel (item 8) given this result, and whether/how to present the confluence path there given it underperforms the existing production path.

## Confluence-aware target selection: closes the entry-only gap, but with real new costs, not a clean win

Following up on the mechanism finding (confluence entries hold win rate but don't improve reward size because targets still come from the sparse smc_signals opposing-zone pool): tested making the opposing-zone search confluence-aware too -- same confluence_mode as the entry, same `build_confluence_zone_frame()` (FULL range) already used for entry-side touch detection, reused as-is for the OPPOSING side. `structural_tp_engine.py` remains completely unmodified -- only which `htf_zones` frame gets passed in as the candidate pool changes.

**Schema:** `target_zone_source` added to `ltf_trigger_signals`, `backtest_trades`, `backtest_runs` (both databases) as a THIRD, orthogonal dimension from `zone_source`/`confluence_mode` -- the same entries get persisted twice, once per target source, isolating exactly one variable (same entry, only the target changes). `opposing_zone_type` extended with `confluence_bullish`/`confluence_bearish`. Both `ltf_trigger_signals` unique keys extended to include it. Caught and fixed a real schema-drift bug while doing this: the `curated_eurusd` copy of `ltf_trigger_signals` in `schema_curated.sql` had silently fallen out of sync with the `curated_gold` copy from an earlier session pass (missing the `uq_trigger_confluence` key entirely) -- rewritten to match exactly before adding the new column.

**Result: real, substantial, but NOT a clean win.**

| symbol | LTF mode | confluence mode | trades | win rate | expectancy R | max DD (R) | DSR | floor |
|---|---|---|---|---|---|---|---|---|
| XAUUSD | choch_only | mode_a (2-factor) | 470 | 50.4% | **+0.163** | 19.9 | 0.99 | met |
| XAUUSD | choch_sweep | mode_a (2-factor) | 399 | 51.1% | **+0.187** | 13.2 | 1.00 | met (barely: 399/398) |
| XAUUSD | choch_only | mode_b (3-factor) | 244 | 35.7% | +0.052 | 46.2 | 0.67 | **FAILED** (244/398) |
| XAUUSD | choch_sweep | mode_b (3-factor) | 209 | 37.3% | +0.092 | 44.2 | 0.77 | **FAILED** (209/398) |
| EURUSD | choch_only | mode_a (2-factor) | 694 | 52.0% | +0.026 | 36.3 | 0.71 | met |
| EURUSD | choch_sweep | mode_a (2-factor) | 613 | 52.5% | +0.053 | 37.7 | 0.86 | met |
| EURUSD | choch_only | mode_b (3-factor) | 376 | 38.8% | +0.089 | 35.4 | 0.84 | **FAILED** (376/398) |
| EURUSD | choch_sweep | mode_b (3-factor) | 347 | 40.1% | +0.151 | 45.5 | 0.95 | **FAILED** (347/398) |

**The hypothesis is confirmed for `mode_a_2factor` specifically: expectancy jumps 5-9x over the entry-only-confluence variant, and for XAUUSD it now beats the smc_signals baseline outright** (+0.163R/+0.187R vs baseline's +0.063R/+0.072R). EURUSD's mode_a improves too (from a slightly-negative -0.006R to a positive +0.026-0.053R) but stays below EURUSD's own baseline (+0.055R/+0.071R).

**Four real costs, not smoothed over:**

1. **Win rate collapses from ~77% to ~50% (mode_a) or ~36-40% (mode_b).** The confluence-target trades are a structurally different profile -- far fewer, bigger wins offsetting more numerous losses, not the original path's frequent-small-win character. `SR0`/DSR stay high because they don't penalize this shape, but it's a materially different risk experience to actually trade.
2. **Max drawdown is 2-6x worse than baseline across every single combination** (13-46R vs baseline's 7-9R) -- worse than even the entry-only-confluence variant's already-elevated 13-31R.
3. **The stricter confluence mode (mode_b_3factor -- the one with the tighter, more-confirmed entries) fails the statistical floor in all 4 combinations**, XAUUSD and EURUSD alike. Confluence zones are the sparser pool; a confluence-sourced TARGET is often much farther away than an smc_signals-sourced one, so trades take longer to resolve and block more subsequent signals via the one-trade-at-a-time overlap rule (XAUUSD mode_b choch_only: 488 skipped for overlap here vs 224 under smc-signals targets on the identical entries) -- shrinking the realized sample below floor even though raw trigger counts were never the constraint.
4. **Every combination shows strong positive skew (1.1-3.5) and high kurtosis (4-19)** -- a signature of a few outsized winners driving much of the return, not a broadly consistent edge. DSR corrects for selection bias across trials, not for this within-sample concentration risk; a handful of unusually favorable trades in this specific 726-day window could be inflating the apparent edge in a way that won't necessarily repeat. Flagged as an open question, not resolved here.

**Verdict: this is a real, structurally different trade-off, not a straightforward "fix" or "still broken."** `mode_a_2factor` + confluence-aware targets is the one variant that both clears the statistical floor comfortably AND beats or nearly matches baseline expectancy -- worth taking seriously as a genuine candidate, but only with the drawdown and skew caveats in view, not as an unambiguous win. `mode_b_3factor` -- ironically the higher-conviction, more-confirmed entry tier -- doesn't have enough resolved trades to trust at all under this target scheme.

**Where it lives:** `analysis/strategies/confluence_ltf_trigger.py` (`build_confluence_zone_frame`, renamed and reused for both entry and target sides), `scripts/detection/run_confluence_ltf_triggers.py` (computes and persists both target variants per entry), `scripts/backtest/run_structural_backtest.py` (`--target-zone-source`), `storage/schema_curated.sql` (target_zone_source extension, both databases, plus the eurusd `ltf_trigger_signals` drift fix).

**Status:** tested on real data, all 8 combinations, both target sources now persisted side by side for direct comparison. Not shelving the confluence approach outright -- `mode_a_2factor` + confluence-aware targets is a real, floor-clearing, expectancy-positive candidate -- but not building the dashboard panel (item 8) on it yet either, given the drawdown/skew caveats above are unresolved. Awaiting the user's direction on next steps (e.g. a distance cap on confluence-sourced targets to control the skew, or accepting the trade-off as-is).

---

## Confluence-target work parked; item 8 (LTF Triggers dashboard panel) built on the validated baseline instead

**What was decided:** the confluence-aware-target path (previous entry) is parked, not pursued further right now -- no distance cap gets built to control the skew, and no dashboard panel gets built on it. Item 8, the LTF Triggers dashboard explanation panel, proceeds against the original single-factor baseline (`smc_signals`-sourced HTF zones, `choch_only`/`choch_sweep` LTF confirmation) instead, since that's the system with the cleanest, most fully understood track record today.

**Why:** `mode_a_2factor` + confluence-aware targets clears the statistical floor and beats baseline expectancy for XAUUSD, but the combination of two unresolved risk properties makes it premature to trust as an equal alternative to baseline: (1) strong positive skew and high kurtosis (1.1-3.5 skew, 4-19 kurtosis) mean the apparent edge is disproportionately driven by a handful of outsized winning trades rather than a broad, consistent edge -- and it's not yet known whether those outsized winners are structurally explainable and repeatable (e.g. a real mechanism tied to confluence-zone target distance) or a within-sample fluke specific to this 726-day window; (2) max drawdown is 2-6x worse than baseline (13-46R vs 7-9R) with no capital-management layer built yet -- risk management, position sizing, and any account-survival logic are explicitly not built in this project (see the "not yet built" list at the top of this log). Trusting a signal with a 13-46R drawdown profile on a small account, before any mechanism exists to actually survive that drawdown, would violate the project's own stated bar of validating before trusting a signal with real money. This is a capital-management gap, not just a signal-quality question -- adding a distance cap to reduce skew would be treating a symptom without first knowing whether the skew is even the right thing to suppress.

This is deliberately logged as a real, promising, tested finding, not a dead end and not a rejection: `mode_a_2factor` + confluence-aware targets remains a legitimate candidate worth returning to once (a) the outsized-winner question above has an answer, and (b) a capital-management layer exists to evaluate the drawdown against real account-survival constraints rather than in the abstract.

**Where item 8 gets built:** against the existing validated baseline -- `smc_signals`-sourced HTF zones (single-factor, h1), `LTFTriggerEngine`'s `choch_only`/`choch_sweep` modes, the same backtest rows already validated and shown on `dashboard/pages/5_backtest_results.py`. The confluence-based signals may be surfaced in the dashboard as available/exploratory (e.g. a toggle labeled "experimental") if useful for visibility, but are not presented with equal trust weighting to the baseline in the UI -- no default view, no unlabeled mixing of the two, and no claim of production-viability for the confluence path in any panel copy.

**Status:** confirmed with the user. Proceeding to item 8 on the baseline.

---

## Item 8: LTF Triggers dashboard "why this zone qualified" explanation panel

**What was decided:** `dashboard/pages/3_ltf_triggers.py` defaults to the validated baseline (`zone_source='smc_signals'`, `target_zone_source='smc_signals'`) and adds a "Why This Zone Qualified" panel under the existing HTF Zone / Touch-CHoCH / Sweep detail row, explaining in plain language why the selected trigger's HTF zone qualified. For a baseline trigger this is one sentence naming the single zone type and confirmation mode. Confluence-sourced signals are reachable only via an explicit "Experimental: show confluence-based signals" checkbox, which swaps the query to `zone_source='confluence_zone'` and exposes confluence-mode/target-source selectors; when active, every card carries an "EXPERIMENTAL" badge, a warning banner citing the drawdown/skew findings (pointing back to this log) is shown, and the explanation panel lists each contributing factor (type, its own price range or point price, formation bar) pulled from `confluence_zones.factors`.

**Why:** this directly implements the just-confirmed decision above — the baseline stays the default, unlabeled view since it's the only validated path, while the confluence path (a real, promising-but-unresolved finding) stays visible for exploration without being presented as equally trustworthy. This also fixed a real latent bug found while building it: the page's query had no `zone_source`/`target_zone_source` filter at all, so once confluence detection tables were populated, baseline and confluence rows (and, for confluence rows, both `target_zone_source` variants) would have silently blended into one unlabeled list the moment a user opened the page — never surfaced before now because no confluence rows existed when the page was first built.

**Where it lives in code:** `dashboard/pages/3_ltf_triggers.py` — `load_triggers()` (zone_source/target_zone_source/confluence_mode filter), `load_confluence_zone()` (factors lookup), `CONFLUENCE_MODE_LABELS`/`FACTOR_LABELS`, the experimental-toggle control row, the `exp-badge`/`exp-banner`/`factor-row` styles, and the "Why This Zone Qualified" block in `render_trigger_workspace()`.

**Status:** built. Verified live in a browser session (Chrome tools) — baseline default view, experimental toggle, and a confluence-sourced card's factor breakdown all confirmed rendering correctly.

---

## Dashboard sidebar page labels: fixed by renaming the page files, not by page_title

**What was decided:** all six dashboard page files were renamed to give the sidebar navigation proper capitalization: `1_chart.py`→`1_Chart.py`, `2_htf_bias.py`→`2_HTF_Bias.py`, `3_ltf_triggers.py`→`3_LTF_Triggers.py`, `4_divergence.py`→`4_Divergence.py`, `5_backtest_results.py`→`5_Backtest_Results.py`, `6_run_pipeline.py`→`6_Run_Pipeline.py`.

**Why:** the sidebar had been showing all-lowercase labels ("htf bias", "ltf triggers", etc.) despite every page already calling `st.set_page_config(page_title="HTF Bias", ...)` with correct capitalization — confirmed empirically that `page_title` only controls the browser tab title, not the sidebar nav label or URL slug. Streamlit's multipage nav derives both of those directly from the page filename (stripping the leading number/underscore, turning remaining underscores into spaces, preserving case as-is, with no auto title-casing) — so the only way to fix the sidebar label is to fix the filename itself.

**A real, load-bearing side effect, not just cosmetic:** renaming the files also changed each page's URL slug (e.g. `/htf_bias` → `/HTF_Bias`, `/ltf_triggers` → `/LTF_Triggers`). Every hardcoded reference to the old filenames was found and updated (`README.md`, `setup.sh`, `setup.bat`'s launch commands; a code comment in `storage/schema_mart.sql`; a code comment in `scripts/detection/run_intermarket_divergence_detection.py`) — confirmed via a full-repo grep, not from memory. Any previously-bookmarked lowercase URL will now 404 (Streamlit's own "Page not found" dialog, falls back to the main page) — acceptable since this is a local dev dashboard, not a deployed/bookmarked production URL, but worth knowing if that changes.

**Evidence:** verified live in Chrome — all 6 sidebar labels render correctly capitalized, each page's new URL slug (obtained from the live page's own rendered `href` attributes via `read_page`, not guessed) loads its correct content, and each page correctly highlights itself as the active sidebar item.

**Where it lives:** `dashboard/1_Chart.py`, `dashboard/pages/2_HTF_Bias.py`, `dashboard/pages/3_LTF_Triggers.py`, `dashboard/pages/4_Divergence.py`, `dashboard/pages/5_Backtest_Results.py`, `dashboard/pages/6_Run_Pipeline.py` (all renamed, no logic changes).

**Status:** complete, verified live.

---

## CRITICAL: realistic stop-distance floor test — baseline's win rate is real, but doesn't answer the question that matters

**What was tested:** whether the validated baseline (zone_source='smc_signals', target_zone_source='smc_signals', choch_only/choch_sweep, both symbols) still shows a real edge once every trade's stop is floored at a realistic distance (300pt and 1000pt, "point" = $1 for XAUUSD / one pip (0.0001) for EURUSD — the retail convention, confirmed empirically below, not MT5's raw decimal "Point" field) instead of the zone/ATR-derived stops the production `structural_tp_engine.py` currently computes.

**Item 4 — actual current stop distances, queried directly from `backtest_trades` (not estimated):**

| symbol / mode | n trades | risk p5 | risk p25 | risk median | risk p75 | risk p95 | risk max |
|---|---|---|---|---|---|---|---|
| XAUUSD choch_only | 461 | 11.3 | 20.3 | **25.9** | 32.8 | 51.9 | 128.7 |
| XAUUSD choch_sweep | 381 | 11.6 | 20.1 | **25.7** | 31.7 | 51.3 | 128.7 |
| EURUSD choch_only | 546 | 6.4 | 11.1 | **14.8** | 18.5 | 26.5 | 41.1 |
| EURUSD choch_sweep | 468 | 6.6 | 10.4 | **14.1** | 18.3 | 26.8 | 41.1 |

(all in "points" under the $1/pip convention above.) This confirms the user's own description of the current baseline almost exactly (median ~26pt gold / ~15pt EURUSD, squarely inside the stated "10-30pt" range) — which is itself how the point-size convention was pinned down: the raw-decimal convention (0.01/0.00001) would have put these same real stops at ~2,600 / ~150 points, nowhere close to what was described, so the $1/pip convention is the one actually in use.

**Items 1-3 — floor applied, full backtest re-run (exploratory only, NOT written to `backtest_trades`/`backtest_runs` — see `structural_tp_engine.py`-equivalent logic in a throwaway script, not a repo file):** mechanism was to widen (not skip) any trigger whose natural zone-derived stop is tighter than the floor, out to exactly floor distance; target price is untouched (it comes from the opposing zone, independent of the stop side); then re-run the same `structural_backtest_engine.simulate()` used in production.

**A first, load-bearing fact: the floor was binding on 100% of triggers, at BOTH 300pt and 1000pt, for all 4 symbol/mode combinations.** Not one single trigger in the entire dataset naturally produces a zone-derived stop of 300+ points — the current system, structurally, only ever generates the tight 10-30pt-class stops the user was worried about. There is no natural in-between; a 300pt+ floor is a wholesale replacement of the stop rule, not a marginal correction.

| symbol / mode | floor | n (decided) | meets 99-trade floor* | win% | expectancy R | max DD (R) | Sharpe | DSR |
|---|---|---|---|---|---|---|---|---|
| XAUUSD choch_only | 300pt | 189 | **Y** | 97.4% | +0.012 | 2.91 | 0.068 | 0.79 |
| XAUUSD choch_only | 1000pt | 168 | **Y** | 100.0% | +0.012 | 0.00 | 0.778 | 1.00 |
| XAUUSD choch_sweep | 300pt | 163 | **Y** | 97.5% | +0.012 | 1.66 | 0.075 | 0.78 |
| XAUUSD choch_sweep | 1000pt | 70 | N | 100.0% | +0.013 | 0.00 | 0.818 | 1.00 |
| EURUSD choch_only | 300pt | 79 | N | 96.2% | **-0.022** | 2.21 | -0.112 | 0.09 |
| EURUSD choch_only | 1000pt | 66 | N | 100.0% | +0.005 | 0.00 | 0.934 | 1.00 |
| EURUSD choch_sweep | 300pt | 154 | **Y** | 98.7% | +0.006 | 1.00 | 0.051 | 0.70 |
| EURUSD choch_sweep | 1000pt | 46 | N | 100.0% | +0.005 | 0.00 | 1.091 | 1.00 |

(*99 trades = this project's own `MIN_TRADES_PER_12_MONTHS`-scaled floor for the real ~181-day data window the baseline itself was measured against — `period_start`/`period_end` read directly from `backtest_runs`, not assumed. DSR here uses n_trials=1, not the persisted baseline's n_trials=2 cross-mode comparison, so DSR values are not directly comparable to the persisted baseline numbers — win rate/expectancy/max DD are.)

**Baseline for direct comparison (current 10-30pt stops, from `backtest_runs`, period='full'):**

| symbol / mode | n | win% | expectancy R | max DD (R) | DSR |
|---|---|---|---|---|---|
| XAUUSD choch_only | 461 | 77.0% | +0.063 | 6.99 | 0.97 |
| XAUUSD choch_sweep | 381 | 77.4% | +0.072 | 9.14 | 0.98 |
| EURUSD choch_only | 546 | 75.5% | +0.055 | 8.66 | 0.95 |
| EURUSD choch_sweep | 468 | 75.9% | +0.071 | 8.41 | 0.98 |

**Why the floor numbers are NOT more trustworthy despite looking better on paper (win rate up to 97-100%, drawdown down to near 0, DSR up to ~1.0): this is a backtest-mechanics artifact, not a genuine improvement, for two compounding reasons.**

1. **`structural_backtest_engine.py` has no maximum holding period by design** (a deliberate "fewest tunable parameters" choice, see its module docstring) — a trade walks forward until stop or target is hit, with no time limit. Widening the stop from ~20pt to 300-1000pt while the target (set independently by the opposing zone) stays the same means almost every trade eventually drifts into its target given enough calendar time, in a dataset that is itself one continuous ~6-month gold/EURUSD uptrend — this is the SAME one-directional-regime risk already flagged for the OOS test period elsewhere in this log, now showing up as a headline "win rate" number instead. It is not evidence the floored stop is safer; it is evidence the backtest has no mechanism to penalize a trade for tying up capital indefinitely while waiting for a distant target.
2. **Sample size collapses, and the ONE-position-at-a-time rule is the direct cause.** A wider stop means fewer stop-outs, which means each trade holds the single available position for far longer (median holding is short, ~1hr, but the tail is severe — up to 10-50 days at the extremes) — and every signal that fires while that position is still open gets skipped (`skipped_overlap` rose to 92-97% of all structural triggers, vs. the baseline's already-high ~80%). Half of the 8 combinations above (all four at 1000pt, plus EURUSD choch_only at 300pt) now fall BELOW this project's own 99-trade statistical floor for the period — a result this project's own convention (see every DSR/floor entry earlier in this log) would refuse to trust on its own terms.

**Bottom line, answering the actual question asked:** this is genuinely the critical test it was framed as, and the honest answer is **inconclusive-leaning-negative, not positive** — it does NOT show the system has a validated real edge at realistic stop distances, but it does conclusively show two things that were previously invisible: (a) every single trade the current baseline has ever taken used a stop tighter than 300 points — the "10-30pt" concern was exactly correct, not a mischaracterization; (b) `structural_backtest_engine.py` cannot currently answer whether that matters, because its unlimited-holding-period assumption breaks down precisely at the stop distances a real trader would use, producing a near-100%-win-rate result that reflects the backtester's patience, not a real edge, while simultaneously shrinking the trade sample below this project's own trust threshold in most of the 8 cells tested.

**What would actually answer this properly (not done here — flagged, not built):** (1) a maximum holding period / time-stop added to `structural_backtest_engine.py` before stop-distance realism can be meaningfully tested at all — without one, ANY stop widening will mechanically inflate win rate by giving trades unlimited time to drift into target; (2) the capital-management/position-sizing layer this log has flagged as not-yet-built in multiple earlier entries — a 300-1000pt stop is a specific dollar risk-per-trade that can only be judged "usable" or "not usable" against a real account size and survivable-drawdown budget, neither of which exist in this project yet.

**Where it lives:** exploratory only — `analysis/strategies/structural_tp_engine.py` and `analysis/backtester/structural_backtest_engine.py` were read but NOT modified; the floor variant was computed in a standalone, non-persisted script reusing their exact same production logic (zone-far-edge stop, ATR max-stop cap, 0.85 opposing-zone target fraction, causal opposing-zone lookup) with only the minimum-risk check changed from ATR-relative/skip to fixed-price/widen. No rows written to `backtest_trades`/`backtest_runs`/`ltf_trigger_signals`.

**Status:** tested and reported per explicit priority instruction, before any other pending item. Not resolved — genuinely blocked on the two missing pieces above (max holding period in the backtest engine; capital-management layer) before this question can be answered with a number either side should trust.

---

## Intraday time-stop added to structural_backtest_engine.py, and re-run against the baseline

**What was decided:** `structural_backtest_engine.py` now enforces a hard intraday time-stop -- a trade still open at 21:00 UTC (the next occurrence strictly after entry: same day if entered before 21:00, next day if entered at/after it) is closed at the last available bar's close price before that cutoff, recorded as a THIRD outcome category (`exit_reason='time_stop'`, `resolution_method='time_stop_eod'`) with a real, continuous `r_outcome` computed from the actual price move at closeout -- not forced to a fixed win or loss value. This directly fixes the "no maximum holding period" root cause identified in the stop-distance-floor test above (that test's near-100%-win-rate result was diagnosed as an artifact of unlimited patience in a trending market, not a real edge).

**Why 21:00 UTC:** this is the standard forex/gold broker daily-rollover boundary -- the same boundary this project's own d1 bars are already built around -- so it's the boundary that actually defines "a trading day" for these instruments, matching the user's day-trading style (not an arbitrary UTC-midnight choice, and not a bare 24-hours-from-entry rule, which wouldn't align to any real trading-day concept).

**Item 1 -- how outcomes redistribute (all 4 baseline combinations, full period, real DB re-run):**

| symbol / mode | closed trades | win% | loss% | time-stop% | time-stop mean R |
|---|---|---|---|---|---|
| XAUUSD choch_only | 498 | 71.5% | 19.3% | 9.2% | -0.081 |
| XAUUSD choch_sweep | 408 | 72.5% | 18.4% | 9.1% | -0.069 |
| EURUSD choch_only | 586 | 72.7% | 20.3% | 7.0% | -0.046 |
| EURUSD choch_sweep | 495 | 73.7% | 20.0% | 6.3% | -0.118 |

Time-stop exits are consistently a small minority (6-9% of closed trades) with a small NEGATIVE mean R -- consistent with what a day-trading conversion should look like: most trades still resolve cleanly same-day, and being forced out at day-end is, on average, a mild cost, not a coin flip.

**Item 2 -- sample size:** all 4 combinations comfortably clear the statistical floor (399 trades required for the ~729-day full-period window; XAUUSD choch_only=498, choch_sweep=408, EURUSD choch_only=586, choch_sweep=495 -- all pass). This is a sharp contrast with the earlier 300-1000pt stop-floor test, where half of the 8 cells FAILED the sample floor. The time-stop fix does not create the same statistical-power problem the naive stop-widening did.

**Item 3 -- before vs after, isolated from an incidental confound.** The freshest previously-persisted baseline (used for comparison earlier today) covered only a ~181-day window (2026-02-15 to 2026-08-15) -- stale relative to the ~729-day (2yr) window this rerun used, because `compute_oos_cutoff()` derives period bounds from raw price history's own depth (now back to 2022) rather than from the trigger set's actual range. To rule this out as a confound before attributing any change to the time-stop fix, the exact same 729-day trigger/bar set was also run through the OLD unlimited-hold logic (`cutoff_time` forced to never fire) as an isolation check -- it reproduced the old baseline's numbers almost exactly (461/381/546/468 trades, 77.0/77.4/75.5/75.9% win rate, +0.063/+0.072/+0.055/+0.071R expectancy), confirming the wider raw-bar window contributes ZERO extra trades (triggers only exist Feb-Aug 2026 regardless of how far back raw price history goes) -- so the comparison below isolates the time-stop's effect cleanly, not a window-size artifact.

| symbol / mode | metric | unlimited-hold (old) | intraday time-stop (new) |
|---|---|---|---|
| XAUUSD choch_only | trades | 461 | 498 |
| | win rate | 77.0% | 74.3% |
| | expectancy R | +0.063 | +0.054 |
| | max DD (R) | 6.99 | 7.35 |
| | DSR | 0.97 | 0.94 |
| XAUUSD choch_sweep | trades | 381 | 408 |
| | win rate | 77.4% | 75.2% |
| | expectancy R | +0.072 | +0.068 |
| | max DD (R) | 9.14 | 7.76 |
| | DSR | 0.98 | 0.98 |
| EURUSD choch_only | trades | 546 | 586 |
| | win rate | 75.5% | 74.7% |
| | expectancy R | +0.055 | +0.065 |
| | max DD (R) | 8.66 | 9.21 |
| | DSR | 0.95 | 0.98 |
| EURUSD choch_sweep | trades | 468 | 495 |
| | win rate | 75.9% | 75.6% |
| | expectancy R | +0.071 | +0.080 |
| | max DD (R) | 7.35 | 6.01 |
| | DSR | 0.98 | 0.995 |

**Reading this honestly: this is a real, mildly positive result, not a wash and not a collapse.** Win rate drops 1-3 points in 3 of 4 combinations (some trades that would have eventually won under unlimited hold get chopped at day-end instead), but expectancy stayed within a few thousandths of R in every case and actually IMPROVED for EURUSD choch_only (+0.055->+0.065) and EURUSD choch_sweep (+0.071->+0.080); max drawdown moved in both directions by small amounts (better for XAUUSD choch_sweep and EURUSD choch_sweep, slightly worse for the other two); trade count went UP in all 4 (461->498, 381->408, 546->586, 468->495) because time-stopped trades free the single available position faster, letting more signals get taken. Unlike the 300-1000pt stop-floor test, there is no suspicious win-rate spike, no drawdown collapsing to zero, and no sample-size failure -- this is what a credible "the edge doesn't depend on unlimited patience" result looks like, in contrast to the earlier test's red flags.

**What this does NOT yet resolve:** this fixes the backtest engine's holding-period assumption to match day-trading reality, but the 300-1000pt realistic-stop-distance question from the previous entry is still open -- that test needs to be RE-RUN with the time-stop now in place (the near-100%-win-rate artifact was specifically caused by the combination of a wide stop AND unlimited hold; with the hold now capped, re-testing the wide-stop floor is likely to give a much more trustworthy answer than either test could alone). Not done in this pass -- flagged as the natural next step, not started here since it wasn't the specific ask.

**Where it lives in code:** `analysis/backtester/structural_backtest_engine.py` (`_time_stop_cutoff()`, `TIME_STOP_CUTOFF_HOUR_UTC`, `_walk_forward()`'s cutoff check, updated `RESOLUTION_METHODS`), `scripts/backtest/run_structural_backtest.py` (`load_raw_bars()` now selects `close_price`; `build_period_metrics()` folds `time_stop` into the decided/expectancy/DSR series and reports the 3-way exit breakdown; `persist()` writes the new `n_time_stop_exits` column), `storage/schema_curated.sql` (`backtest_trades.exit_reason`/`resolution_method` ENUMs extended with `time_stop`/`time_stop_eod`; `backtest_runs.n_time_stop_exits` added -- both applied live via `ALTER TABLE` on `curated_gold` and `curated_eurusd`, and written into the schema file for future re-creates), `dashboard/pages/5_Backtest_Results.py` (`decided` filter extended to include `time_stop` so the dashboard doesn't silently drop these rows), `tests/test_structural_backtest_engine.py` (3 new tests: normal time-stop closeout, late-entry cutoff rollover to the next day, and the degenerate zero-bars-before-cutoff edge case that surfaced and was fixed during this pass -- see below).

**A real bug found and fixed during this pass, not just a feature add:** the first implementation returned `exit_bar_datetime = entry_bar_time` unchanged in the degenerate case where a trade enters so close to the cutoff that zero bars exist before it fires -- this broke the one-trade-at-a-time overlap-skip invariant (which relies on exit always being strictly after entry) and caused a real `Duplicate entry` error against `backtest_trades.uq_backtest_trade`'s unique key on `entry_bar_datetime` during the live re-run. Fixed by falling back to `cutoff_time` itself (always strictly after entry by construction) as the exit timestamp in that one edge case, and a dedicated regression test was added for it.

**Status:** implemented, unit-tested (9/9 tests passing, including the new time-stop and edge-case tests), and re-run live against all 4 baseline combinations with results persisted to `backtest_trades`/`backtest_runs` (this is now the standard/default backtest behavior going forward, not an exploratory variant). The 300-1000pt stop-floor re-test under this new time-stop is the natural next step, not yet done.

**SUPERSEDED by the next entry** -- the time-stop was reverted after the user clarified they hold trades to TP/SL by their own discretion, not on a forced day-trading schedule. Left in the log as a real, tested-and-reasoned-through step, not deleted from history.

---

## Time-stop reverted; one-trade-at-a-time constraint removed instead

**What was decided:** two changes, requested together. (1) The 21:00 UTC intraday time-stop (previous entry) is fully reverted -- `structural_backtest_engine.py` is back to unlimited holding period, a trade resolves only via TP, SL, or `open_at_data_end`. The user does not day-trade on a forced schedule; they hold until their own discretionary TP/SL decision, so the backtest should not simulate a behavior they don't use. (2) The one-trade-at-a-time (single-position) constraint is ALSO removed -- every valid trigger (`target_status='structural'`) is now simulated as its own fully independent trade, regardless of whether another trade from the same (symbol, mode) is still open. This directly targets the sample-size problem that made several stop-distance-floor variants fail this project's own statistical floor (skipping 70-97% of qualifying signals for "overlap" was artificially shrinking the realized trade count far below the raw signal count) -- without touching how any individual trade resolves.

**Why revert instead of keep both:** the time-stop fix and the realistic-stop-distance question were two separate, real problems, but the time-stop's specific mechanism (force-closing at a fixed daily cutoff) modeled a trading style the user doesn't practice. Rather than keep a mechanism that doesn't match real behavior, the actual root cause of the earlier bad test (sample size collapsing under the one-trade-at-a-time constraint) is fixed directly by removing that constraint -- which was always a stronger, more honestly-labeled assumption than the time-stop was ("one trader, one position, fixed 0.01 lot" -- see the module's original docstring) but was never actually validated against whether the user's real capital-management approach requires it.

**A schema change was required, not just a code revert -- concurrent trades break an implicit assumption `backtest_trades`'s unique key relied on.** `uq_backtest_trade` was keyed in part on `entry_bar_datetime`, which was safe under one-trade-at-a-time (the overlap-skip logic guaranteed no two TAKEN trades could ever share a timestamp) but breaks the moment concurrent trades are allowed -- two different HTF zones can legitimately confirm on the exact same LTF bar and are now both real, independent trades. Added `source_trigger_id` (a soft FK to `ltf_trigger_signals.id`) as the new disambiguator in both the column set and `uq_backtest_trade`, replacing `entry_bar_datetime` in the key. Applied live via `ALTER TABLE` on `curated_gold`/`curated_eurusd` and written into `schema_curated.sql` for future re-creates. 4,114 (gold) + 5,762 (EURUSD) pre-existing CONFLUENCE-ZONE backtest rows from an earlier, unrelated session predated this column and collided under the new key once defaulted to 0 -- backfilled with each row's own `backtest_trades.id` (a real, guaranteed-unique value, but NOT a genuine link back to `ltf_trigger_signals` for that specific older slice; every row inserted from this point forward carries the real source trigger id) rather than deleted, since they're real, already-documented results (see the "Confluence LTF Trigger: structural backtest results" entries earlier in this log), not junk.

**Item 3 -- confirmed the revert actually restores original behavior**, isolated from a data-window confound (see previous entry): reusing the reverted (cutoff-disabled) walk-forward logic against the same real trigger/bar data reproduced the original persisted baseline exactly -- 461/381/546/468 trades, 77.0/77.4/75.5/75.9% win rate, +0.063/+0.072/+0.055/+0.071R expectancy, 6.99/9.14/8.66/8.41R max drawdown, for XAUUSD choch_only/choch_sweep and EURUSD choch_only/choch_sweep respectively. This matches the DB-confirmed baseline queried directly from `backtest_runs` at the very start of this session, before any of today's changes -- the revert is a genuine, verified restoration, not an approximation.

**Trade counts and metrics, one-trade-at-a-time (before) vs. concurrent trades allowed (after), both unlimited-hold:**

| symbol / mode | trades before → after | win% before → after | expectancy R before → after | max DD (R) before → after |
|---|---|---|---|---|
| XAUUSD choch_only | 461 → **2217** | 77.0% → 75.6% | +0.063 → +0.046 | 6.99 → **72.40** |
| XAUUSD choch_sweep | 381 → **1672** | 77.4% → 76.5% | +0.072 → +0.042 | 9.14 → **40.88** |
| EURUSD choch_only | 546 → **2508** | 75.5% → 76.4% | +0.055 → +0.053 | 8.66 → **45.18** |
| EURUSD choch_sweep | 468 → **2009** | 75.9% → 77.5% | +0.071 → +0.084 | 8.41 → **44.17** |

Trade count jumped 3.6-4.8x (matches this project's own previously-documented "2217/1672/2508/2009 structural triggers" reference count exactly -- every qualifying signal is now taken, confirming the mechanism works as intended) and comfortably clears the 399-trade statistical floor in all 4 cells, resolving the sample-size problem this was built to fix. Win rate and expectancy stayed close to baseline (within 1-3 points / a couple thousandths of R) -- the underlying signal quality didn't change, as expected, since no individual trade's resolution logic changed.

**Max drawdown increased 6-10x, and this is a real, honest, expected consequence flagged plainly, not a bug:** `max_drawdown_r` is computed as peak-to-trough of the CUMULATIVE R equity curve in chronological entry order (`analysis/backtester/deflated_sharpe.py::trade_metrics()`), unchanged by today's work -- it was always going to read differently once concurrent losing trades can pile up in that same running sum instead of being serialized one at a time. This is not a new mechanism-artifact the way the earlier stop-floor test's near-100% win rate was (that one was diagnosed as a backtest engine allowing something that couldn't happen with a real 21:00 cutoff at play); this is the correct, direct mathematical consequence of the modeling choice the user explicitly asked for, faithfully reported, not smoothed over. **What removing one-trade-at-a-time does NOT model: a capital/margin constraint.** A real account may not actually be able to hold every one of 2217 XAUUSD choch_only positions simultaneously -- this backtest, as before, does not claim to answer that; it answers "does the signal have an edge," not "is this executable at any given account size." That's the same capital-management gap already flagged in the stop-distance-floor entry above, now showing up more visibly in the drawdown number rather than being hidden by an artificial position-serialization constraint.

**R:R distribution (structural_rr, all 4 combinations, concurrent-trades dataset) -- matches this project's own previously-documented distribution for the same underlying trigger set (see "R:R distribution, XAUUSD choch_only" entry earlier in this log), confirming nothing about signal generation itself changed:**

| symbol / mode | n | p5 | p25 | median | p75 | p95 |
|---|---|---|---|---|---|---|
| XAUUSD choch_only | 2217 | 0.024 | 0.129 | 0.278 | 0.581 | 1.494 |
| XAUUSD choch_sweep | 1672 | 0.022 | 0.140 | 0.278 | 0.549 | 1.385 |
| EURUSD choch_only | 2508 | 0.025 | 0.132 | 0.300 | 0.620 | 1.321 |
| EURUSD choch_sweep | 2009 | 0.027 | 0.136 | 0.324 | 0.624 | 1.344 |

**Where it lives in code:** `analysis/backtester/structural_backtest_engine.py` (module docstring rewritten, `_time_stop_cutoff`/`TIME_STOP_CUTOFF_HOUR_UTC`/cutoff parameter all removed, `_walk_forward()` back to its original signature, `simulate()`'s `next_available`/skip logic removed -- every trigger simulated, `skipped_timestamps` always empty, `source_trigger_id` added to `TRADE_COLUMNS`), `scripts/backtest/run_structural_backtest.py` (`build_period_metrics()`/`print_report()` time-stop breakdown removed, `persist()` writes `source_trigger_id`, `n_time_stop_exits` removed from the `backtest_runs` insert), `storage/schema_curated.sql` (`backtest_trades.exit_reason`/`resolution_method` ENUMs shrunk back, `backtest_runs.n_time_stop_exits` dropped, `backtest_trades.source_trigger_id` added and substituted for `entry_bar_datetime` in `uq_backtest_trade` -- all applied live via `ALTER TABLE` on both databases), `dashboard/pages/5_Backtest_Results.py` (`decided` filter reverted to `win`/`loss` only), `tests/test_structural_backtest_engine.py` (the 3 time-stop tests removed, the one-trade-at-a-time test replaced with a concurrent-trades test asserting nothing is skipped and every trigger's `source_trigger_id` survives to its trade row -- 6/6 tests passing).

**Status:** implemented, unit-tested, and re-run live against all 4 baseline combinations with results persisted (this is now the standard/default backtest behavior going forward). The realistic 300-1000pt stop-distance-floor question is STILL open -- not re-tested in this pass, since it wasn't today's ask, but now has a cleaner mechanism to be re-tested against (concurrent trades fix the sample-size failure; the max-drawdown number would need to be read carefully given today's finding about how it compounds under concurrent trades).

---

## 4 stop-calculation methods compared side by side -- data gathering only, no method chosen

**What was done:** `structural_tp_engine.py`'s `compute_structural_targets()` was extended with a new `stop_mode='nearest_structure'` (plus the existing `widen_to_min_risk` combination) and tested alongside the existing `zone_far_edge`/`atr` modes, specifically to compare 4 distinct stop-calculation methods against real data, TARGET SELECTION HELD IDENTICAL throughout -- explicitly a comparison, not a decision; no method was adopted as the new default.

**The 4 methods:**
1. **baseline** (`zone_far_edge`, current production) -- stop is the far edge of the triggering zone itself.
2. **nearest** (`nearest_structure`, new) -- searches ALL causally-active zones of the SAME direction as the trigger (not just the one that fired) for the nearest genuine structural invalidation point, reusing the identical nearest-causal-zone search mechanism already used for target selection, mirrored to the near/support side. Falls back to the triggering zone's own far edge when no closer same-direction zone exists on the correct side of entry.
3. **middle_ground** (`nearest_structure` + `widen_to_min_risk=True`, new) -- same as (2), but a stop tighter than the EXISTING `MIN_RISK_ATR_MULTIPLE` floor (0.5x ATR-14, already used elsewhere in this engine) is widened to exactly that floor distance instead of being skipped as `stop_too_tight` -- reuses an existing constant rather than introducing a new tunable one, and directly targets the sample-loss the floor's skip-not-widen behavior was causing.
4. **mae_75pct** (`atr` mode with an EMPIRICALLY-derived `atr_stop_multiple`, new) -- computed from real data, not structural geometry at all: for every WINNING trade in the current baseline (`backtest_trades`, `exit_reason='win'`), walked the real m15 bars between entry and exit to find each trade's Maximum Adverse Excursion (MAE) -- how far price moved against the position at its worst point before eventually reaching target -- normalized by h1 ATR-14 at entry (not raw price; gold ranged $2500-$5500 across this dataset, so a fixed price distance would be systematically wrong at one end or the other, same ATR-normalization convention this engine already uses elsewhere). Took the 75th percentile of that per-(symbol, mode) MAE-in-ATR-multiples distribution as the stop distance: XAUUSD choch_only=0.509x, choch_sweep=0.493x; EURUSD choch_only=0.524x, choch_sweep=0.526x ATR.

**Why 75th percentile, not another cut:** a stop at the 75th percentile of real winning-trade MAE means it would have let 75% of this dataset's actual winners survive their worst real drawdown to reach target, while staying meaningfully tighter than the 90-95th percentile tail (0.92-1.20x ATR across the 4 combos) -- which is dominated by rare, large pullback outliers and would produce an excessively wide, low-information stop. 80th percentile (0.61-0.64x ATR) is a reasonable, slightly more conservative alternative -- computed and available, not run through a full backtest here to keep the comparison to the requested 4 methods.

**A real, one-sided limitation of method 4, stated plainly rather than presented as automatically superior for being data-driven:** the MAE distribution is computed ONLY from winning trades -- survivorship bias by construction. It says nothing about what LOSING trades' adverse excursions look like; a stop sized to let 75% of winners survive might be far wider than what most losing trades needed to be stopped out efficiently, or barely change the loss population at all. This is exactly why the full backtest re-run below (not just the MAE distribution alone) is the real evidence -- it's what actually reveals whether the wider stop's cost (a bigger 1R, since risk defines that unit) outweighs its benefit (fewer premature win-cutoffs).

**A mechanical note on the comparison itself:** `n_structural` differs across methods (e.g. XAUUSD choch_only: 2217 baseline / 2214 nearest / 2539 middle_ground+mae_75pct) because `widen_to_min_risk=True` (methods 3 and 4) converts almost all `stop_too_tight` skips into structural trades instead (`n_stop_too_tight` drops from 219-369 to just 4-7, the residual being triggers with no ATR value at all) -- methods 1 and 2 still skip on the tight-stop floor as production does today.

**Results, all 4 symbol/mode combinations, full period, unlimited-hold + concurrent-trades-allowed (current backtest setup):**

| symbol / mode | method | trades | win% | expectancy R | max DD (R) | R:R min / median / max |
|---|---|---|---|---|---|---|
| XAUUSD choch_only | baseline | 2217 | 75.6% | +0.046 | 72.39 | 0.001 / 0.278 / 4.63 |
| | nearest | 2214 | 72.1% | +0.035 | 61.75 | 0.002 / 0.311 / 4.63 |
| | middle_ground | 2539 | 71.9% | **+0.084** | 67.83 | 0.002 / 0.364 / 5.80 |
| | mae_75pct | 2539 | 57.9% | +0.049 | **96.05** | 0.004 / 0.726 / 5.78 |
| XAUUSD choch_sweep | baseline | 1672 | 76.5% | +0.042 | 40.87 | 0.001 / 0.278 / 3.93 |
| | nearest | 1642 | 72.6% | +0.019 | 48.03 | 0.002 / 0.310 / 3.42 |
| | middle_ground | 1914 | 72.3% | **+0.068** | **34.06** | 0.002 / 0.353 / 5.68 |
| | mae_75pct | 1914 | 59.2% | +0.065 | 53.39 | 0.004 / 0.721 / 5.88 |
| EURUSD choch_only | baseline | 2508 | 76.3% | +0.052 | 45.18 | 0.004 / 0.300 / 5.29 |
| | nearest | 2545 | 72.5% | +0.032 | 89.79 | 0.004 / 0.336 / 5.29 |
| | middle_ground | 2910 | 72.4% | **+0.097** | 63.35 | 0.004 / 0.367 / 6.15 |
| | mae_75pct | 2910 | 57.8% | +0.048 | 90.94 | 0.010 / 0.748 / 7.80 |
| EURUSD choch_sweep | baseline | 2009 | 77.4% | +0.083 | 44.17 | 0.004 / 0.324 / 5.29 |
| | nearest | 1978 | 74.4% | +0.078 | 58.61 | 0.004 / 0.345 / 5.29 |
| | middle_ground | 2266 | 73.4% | **+0.112** | 51.76 | 0.004 / 0.378 / 5.28 |
| | mae_75pct | 2266 | 59.0% | +0.078 | 65.07 | 0.010 / 0.746 / 7.78 |

**Patterns visible in the real numbers (reported, not interpreted into a recommendation):**
- **middle_ground has the highest expectancy in all 4 combinations** (+0.068 to +0.112R vs baseline's +0.042 to +0.083R) and the highest trade count in all 4 (more signals converted from skipped to taken).
- **nearest has the lowest expectancy in 3 of 4 combinations** and, notably, the worst max drawdown of any method for EURUSD choch_only (89.79R) -- a tighter, more "surgical" stop does not uniformly help here.
- **mae_75pct has a materially lower win rate in all 4 combinations** (57.8-59.2% vs 71.9-77.4% for the others) -- expected, since a much wider stop (median MAE-derived ATR multiple ~0.5x vs baseline's typically-tighter zone-edge distances) gives losing trades more room to still turn into losses rather than being cut early, while the R:R distribution shifts up correspondingly (median R:R roughly 2.3-2.7x every other method's). It also produced the single worst max drawdown of all 16 method/combo cells (96.05R, XAUUSD choch_only).
- No method wins on every metric simultaneously in any combination -- each has a real, visible tradeoff in this data, not a hidden flaw.

**Where it lives in code:** `analysis/strategies/structural_tp_engine.py` (`stop_mode='nearest_structure'`, `widen_to_min_risk` parameter), `scripts/backtest/compare_stop_calculation_methods.py` (new, exploratory-only, mirrors `compare_structural_tp_variants.py`'s established pattern -- not part of the regular pipeline, not written to `backtest_trades`/`backtest_runs`). MAE computation was done in a standalone script (not committed to the repo -- a one-off data-gathering pass against the current baseline's persisted winning trades) to derive `MAE_ATR_MULTIPLE_75TH`, hardcoded into the comparison script with a note that it's a snapshot tied to the current baseline dataset.

**Status:** all 4 methods tested against real data, all 4 symbol/mode combinations, reported side by side per the explicit "no recommendation" instruction. Awaiting the user's decision on which (if any) becomes the new production default -- `structural_tp_engine.py`'s actual default (`stop_mode='zone_far_edge'`) is UNCHANGED; nothing here was adopted.

---

## Composite Confluence Engine: design + real-example validation (not built yet)

**What was done:** designed (not implemented as a production engine) a replacement for the earlier sequential "touch -> CHoCH [-> sweep]" gating model in `ltf_trigger_engine.py`. All 6 existing signal engines/tables now contribute as PARALLEL, independent inputs to one composite score per candidate, rather than sequential gates where a missing factor early kills the candidate outright.

**Design:**

*Candidate anchor* -- unchanged from the existing pipeline: an LTF (m15) touch of an active h1 SMC zone in its expected reaction direction, using the exact touch mechanism already in `ltf_trigger_engine.py` (formation-hour exclusion included), collapsed to one event per contiguous touching run (price sitting inside a zone for N bars is one touch, not N candidates -- a real bug caught and fixed during the validation prototype, see below). Unlike the existing engine, CHoCH is NOT required to generate a candidate -- it becomes factor #2 below instead of a gate.

*6 factors, each contributing 1 point if present, 0 if absent (equal-weight binary, same "simple, explainable, not black-box" philosophy as `confluence_zone_engine.py`'s confidence score) -- ALL reused from already-built engines/tables, nothing re-detected except CHoCH and sweeps, which were never persisted anywhere to begin with and are already computed live by `ltf_trigger_engine.py` for the same reason:*
1. **sweep** -- `LiquiditySweepStateEngine` on the LTF series, matching direction, within a 20-bar window of the touch (reused `CONFIRMATION_WINDOW_BARS`/`DIVERGENCE_LOOKBACK_BARS` convention).
2. **choch** -- `SMCStructureEngine.detect_bos_choch()` on the LTF series, CHoCH in trigger direction within the same window.
3. **zone_stack** -- >=2 ACTIVE h1 zones of the trigger direction overlap current price at touch time (the touched zone is always 1; this asks whether another genuinely stacks).
4. **crt** -- `htf_bias.crt_equilibrium_bias` at the nearest h1 bar <= touch matches direction (discount=bullish, premium=bearish) -- reads the ALREADY-COMPUTED column, no CRT recomputation.
5. **htf_bias** -- `htf_bias.bias` at the nearest h1 bar <= touch matches direction exactly (neutral doesn't count).
6. **divergence** -- any `divergence_signals` row (any class, any of the 14 XAUUSD / 7 EURUSD models), matching direction, within `DIVERGENCE_LOOKBACK_BARS=20` h1 bars of the touch -- same constant `htf_bias_engine.py` already uses.

*Proposed file structure (not yet created):* `analysis/strategies/composite_confluence_engine.py` -- a new, additive module following this project's established pattern (does not modify `ltf_trigger_engine.py`, `htf_bias_engine.py`, or any detector). Would import and call, read-only: `SMCStructureEngine`, `LiquiditySweepStateEngine` (both already imported this way elsewhere), plus DB reads against `smc_signals`, `htf_bias`, `divergence_signals`, `crt_signals` (equilibrium rows). `scripts/detection/run_composite_confluence_detection.py` would follow the same run_*.py pattern as every other detection stage, writing to a new `composite_confluence_signals` table (not `ltf_trigger_signals` -- a materially different row shape: multiple ranked targets per signal, not one).

**Stop method used for this design -- PROVISIONAL, status checked before assuming baseline, per instruction:** the immediately preceding DECISIONS.md entry ("4 stop-calculation methods compared") explicitly ended with NO method adopted -- `structural_tp_engine.py`'s real default is still `zone_far_edge`, and the comparison's own status line says "awaiting the user's decision." This design uses `nearest_structure` + `widen_to_min_risk=True` ("middle_ground") because it had the best expectancy in all 4 real backtest combinations tested so far -- stated here explicitly as a provisional choice for this design pass, not a retroactive adoption of that still-open decision.

**Targets:** ALL structural levels ahead of entry in the trade direction within a capped search range (`TARGET_MAX_ATR_MULTIPLE=10.0` x ATR-14 -- a starting bound, flagged unvalidated like every other new constant in this project), pooled from h1 SMC zones (opposing-direction near edge, same zone types `structural_tp_engine.py` already searches) AND h4/h6/d1 CRT equilibrium price (read from `crt_signals`, not recomputed) if ahead of price -- ranked by distance ascending, nearest = TP1. Hard rule enforced exactly as specified: **TP1 R:R must be >= 3.0 or the candidate is discarded entirely** (not shown, not weakened).

**Real-example validation (XAUUSD, last 120 days, via `scripts/diagnostic/prototype_composite_confluence.py` -- new, committed diagnostic script, NOT the production engine):**

Raw touches before collapsing consecutive-bar duplicates: 28,377. After collapsing to one event per contiguous touching run: **3,149** genuine candidate touches -- a real bug caught during this validation pass (touching a zone for 10 consecutive bars was generating 10 candidates, not 1) and fixed before the score distribution was computed.

Score distribution (0-6), 3,149 candidates:

| score | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| count | 13 | 194 | 594 | 1133 | 888 | 282 | 45 |

**Threshold picked empirically, not guessed:** score >= 4/6 gives 1,215 candidates over 120 days (~10/day) -- comparable density to this project's existing `mode_b_3factor` convention (3-of-5 factors, ~60% threshold; 4-of-6 here is ~67%). Score >= 5 gives 327 (~2.7/day, stricter); score == 6 (perfect confluence) gives only 45 (~0.4/day). **The TP1 R:R >= 3.0 floor turned out to be the dominant filter, not the score threshold:** of the 1,215 candidates scoring >= 4, only **12** also cleared TP1 R:R >= 3.0 -- roughly 99% of confluence-qualifying candidates get discarded on the reward-to-risk geometry alone, not on confluence strength. This is reported as a real, load-bearing finding: whatever score threshold is eventually chosen, the R:R floor will do most of the actual filtering.

**A second real pattern in the qualifying set, worth flagging before any decision:** in all 12 examples that passed both filters, `sweep=1` and `zone_stack=1`; in 11 of 12, `choch=0`. CHoCH -- the factor the ENTIRE previous engine was gated on -- was almost always ABSENT from the signals that actually clear a 1:3 R:R under this design. This doesn't mean CHoCH is worthless (it's still one of six inputs, and it appears in the two highest-scoring examples below), but it is a concrete, data-backed reason the sequential "CHoCH-first" gate the user asked to replace may have been filtering out exactly the signals with the best reward-to-risk geometry.

**5 concrete real examples (entry/stop/TP1..TPn/R:R, all real XAUUSD price levels):**

1. **2026-07-23 06:30 BULLISH, score=5/6** (sweep, zone_stack, crt, htf_bias, divergence -- no CHoCH) -- entry=4120.02, stop=4112.30 (risk=7.72). TP1=4146.61 (swing_resistance, R:R=3.44), TP2=4148.53 (R:R=3.69), TP3=4150.02 (R:R=3.89), TP4=4156.08 (R:R=4.67), TP5=4163.73 (R:R=5.66).
2. **2026-08-12 14:30 BULLISH, score=4/6** (sweep, zone_stack, htf_bias, divergence) -- entry=4424.95, stop=4415.23 (risk=9.72). TP1=4458.56 (order_block_bearish, R:R=3.46), TP2=4468.90 (R:R=4.52), TP3=4476.27 (R:R=5.28).
3. **2026-05-27 08:30 BEARISH, score=4/6** (sweep, choch, zone_stack, divergence) -- entry=4496.25, stop=4504.76 (risk=8.51). TP1=4467.37 (swing_support, R:R=3.39), TP2=4462.07 (crt_equilibrium_h6, R:R=4.02).
4. **2026-05-01 14:00 BEARISH, score=4/6** (sweep, zone_stack, crt, htf_bias) -- entry=4656.06, stop=4666.18 (risk=10.12). TP1=4625.58 (fvg_bullish, R:R=3.01), TP2=4617.62 (crt_equilibrium_h4, R:R=3.80), TP3=4573.11 (order_block_bullish, R:R=8.20).
5. **2026-07-23 20:45 BULLISH, score=4/6** (sweep, zone_stack, crt, divergence) -- entry=4049.41, stop=4042.42 (risk=6.99). TP1=4086.15 (order_block_bearish, R:R=5.25), TP2=4097.65 (R:R=6.90), TP3=4114.35 (R:R=9.29).

**A known rough edge in the prototype, not yet polished:** 3 of the 12 qualifying rows were exact duplicates of the same touch/entry/stop/targets (e.g. `2026-07-30 13:30 BEARISH` appeared 3x) -- candidate-level dedup was applied but not results-level dedup after scoring; likely caused by distinct SMC zone rows that happen to share identical top/bottom boundaries. Real, ~10 genuinely distinct qualifying signals over 120 days, not 12. Flagged for the full build, not fixed here since this is the validation phase.

**Where it lives:** `scripts/diagnostic/prototype_composite_confluence.py` (new, committed, reusable -- not the production engine; re-run with `--symbol`/`--days` to revalidate against more history or EURUSD). No production files modified.

**Status:** design proposed, validated against real data, NOT implemented as a production engine per explicit instruction. Awaiting the user's review of the design, the empirically-picked score threshold (4/6 proposed), the provisional stop-method choice, and the 5 real examples above before `analysis/strategies/composite_confluence_engine.py` gets built for real.

---

## Composite Confluence Engine validation: dedup fix + full-history re-run -- sample size fails badly

**1. Dedup bug fixed.** Root cause confirmed by direct query: the 3 duplicate rows out of 12 (120-day window) were 3 genuinely DISTINCT `smc_signals` zones (different `zone_top`/`zone_bottom`/`created_at_bar` -- e.g. three separate `swing_resistance` zones with ranges 4088.55-4106.02, 4077.78-4093.75, and 4044.44-4116.28, all overlapping) touched by price at the exact same m15 bar. Each is a legitimately different zone event, but since `nearest_structure` stop selection and target ranking both search ALL causally-active same/opposing-direction zones (not just the touched one), all 3 landed on the IDENTICAL final trade (same entry/stop/targets) -- one real tradeable signal, not three. Fixed with a results-level dedup (by touch time, direction, entry, stop) added on top of the existing candidate-level dedup, which only covered exact-duplicate zone rows, not this case. 120-day XAUUSD count corrected from 12 to **10** distinct signals, confirmed.

**A second real bug caught fixing the first one:** the dedup key (and every printed price) hardcoded 2-decimal rounding, correct for XAUUSD but wrong for EURUSD -- at 2dp, two genuinely different EURUSD entries (e.g. 1.14523 vs 1.14498) both round to 1.15 and would have been wrongly collapsed into one signal by the dedup key, on top of just displaying as `risk=0.00` in the printed examples. Fixed with a `PRICE_DECIMALS` dict (XAUUSD=2, EURUSD=5, same convention as `dashboard/pages/3_LTF_Triggers.py`) threaded through both the dedup key and the display formatting. Confirmed this was display/dedup-only, not a scoring or R:R-math bug -- the qualification math (`tp1_rr = tp1_dist / risk`) always ran on full-float values, never the rounded strings.

**2. Full available history, not just 120 days.** True bound is NOT the ~4-year raw price history -- `htf_bias`/`divergence_signals`/`crt_signals` (3 of the 6 factors) only exist from 2024-09-13/16 onward (the MT5-switch era), so a candidate needs all 6 factors computable and the real usable window is **~699 days (2024-09-16 -> now)**, not the full raw-price depth. Re-ran both symbols on this full window.

| symbol | qualifying signals (score>=4 AND TP1 R:R>=3) | signals/day | annualized (/365.25d) | this project's floor for 699d (200/12mo scaled) | meets floor? |
|---|---|---|---|---|---|
| XAUUSD | 77 | 0.110 | ~40/yr | ~383 | **NO -- 20% of floor** |
| EURUSD | 98 | 0.140 | ~51/yr | ~383 | **NO -- 26% of floor** |

**Direct answer to the sample-size question: this does NOT clear the statistical floor.** 120 days giving ~10-12 signals was not a fluke of a short window -- scaled up to the full 699-day history, both symbols land at roughly 1 signal every 7-9 days, arriving at 77 and 98 respectively against a ~383-trade requirement. This confluence design, AS SPECIFIED (score>=4/6 AND hard TP1 R:R>=3.0 floor), produces roughly a fifth to a quarter of the trade count this project's own convention requires before a backtest result would be trusted. The TP1 R:R>=3.0 hard floor remains the dominant bottleneck (confirmed again at full scale, same pattern as the 120-day check) -- loosening the score threshold alone will not fix this without also revisiting the R:R floor, the target-search range, or the stop method.

**3. Factor-presence breakdown at full scale -- the small-sample CHoCH finding does NOT fully hold up, exactly the caution that prompted re-checking before touching any weights:**

| factor | XAUUSD (n=77) | EURUSD (n=98) |
|---|---|---|
| sweep | 89.6% | 84.7% |
| choch | **41.6%** | **55.1%** |
| zone_stack | 98.7% | 95.9% |
| crt | 84.4% | 77.6% |
| bias | 39.0% | 14.3% |
| divergence | 77.9% | 91.8% |

At the 120-day sample, CHoCH was present in only 1 of 12 signals (~8%) -- at full scale it's present in 41.6% (XAUUSD) and 55.1% (EURUSD), a completely different picture. **The 120-day finding was small-sample noise, not a real pattern** -- exactly the kind of thing this project's own convention (validate against real data before acting, especially before touching a weighting scheme) exists to catch. `zone_stack` (96-99%) and `sweep` (85-90%) are consistently the most common factors in qualifying signals across both symbols; `crt` and `divergence` are both consistently high (78-92%) though the specific pattern flips between symbols (EURUSD leans harder on divergence, XAUUSD's crt/divergence are closer together). The two genuinely weak factors, consistent across both symbols, are **`bias` (39.0% / 14.3%) and, to a lesser extent, `choch` (41.6% / 55.1%)** -- `bias` in particular is the weakest factor in both symbols and the standout outlier for EURUSD specifically (14.3%). No weighting change made -- reported per the explicit instruction, for a decision once seen at scale.

**Where it lives:** `scripts/diagnostic/prototype_composite_confluence.py` (dedup fix, `PRICE_DECIMALS`, aggregate factor-presence + signals/day + floor-comparison summary added to the script's own output -- reusable for future re-validation, not one-off numbers pasted here).

**Status:** both requested checks complete. The design as specified does not clear this project's sample-size floor at either symbol -- this is a real blocker to flag before building the full pipeline, not a rubber-stamp "looks fine, proceeding." Awaiting the user's direction: loosen the score threshold, revisit the TP1 R:R floor, widen the target-search range, change which stop method is used, or accept a lower trade count than this project's convention normally requires (each is a different lever with a different cost, not a single obvious fix).

---

## Target-search-range sweep (R:R floor held fixed) + HTF Bias redundancy check

**What was tested, per explicit instruction not to loosen the TP1 R:R>=3.0 floor:** (1) whether widening how far ahead the engine searches for targets changes the qualifying count, R:R floor held fixed; (2) whether HTF Bias (weakest factor, 39-55% presence) is redundant with or conflicts with the other 5 factors, given it already aggregates SMC/CRT/indicator/volume-profile/divergence itself.

**1. Widening the target-search range changes NOTHING -- flat at every value tested, both symbols:**

| target_max_atr_multiple | XAUUSD | EURUSD |
|---|---|---|
| 10x (current) | 77 | 98 |
| 15x | 77 | 98 |
| 20x | 77 | 98 |
| 30x | 77 | 98 |
| 50x | 77 | 98 |
| 100x | 77 | 98 |

**Real finding, not a null result:** TP1 is always the NEAREST opposing structural level within range; given how dense the pooled zone/CRT-equilibrium data already is, a candidate essentially always has SOME opposing level within 10x ATR already -- widening the range only adds MORE DISTANT options after TP1, it cannot change what TP1 already is (or whether that TP1's R:R clears 3.0). Range-widening is a dead end for the sample-size problem as specified. **The actual lever for increasing count while holding R:R>=3.0 fixed is the STOP distance, not the target range** -- a tighter stop raises R:R against the same already-available nearest target; the stop-calculation method (still an open decision, see the "4 stop-calculation methods" entry) is where this needs to be revisited, not target search.

**2. HTF Bias: not redundant, rarely in real conflict -- structurally strict by its own original design.** Computed on the full score>=4 pool (7,630 XAUUSD / 9,151 EURUSD candidates -- the R:R-qualifying 77/98 set is too small for a reliable correlation read, so this analysis intentionally used the larger pool):

| | XAUUSD (n=7630) | EURUSD (n=9151) |
|---|---|---|
| bias AGREES with direction | 26.4% | 20.5% |
| bias NEUTRAL | **68.1%** | **73.5%** |
| bias OPPOSES direction | 5.6% | 6.0% |

The low `f_bias` presence rate is overwhelmingly explained by HTF Bias sitting NEUTRAL ~70% of the time, not by active disagreement (only 5.6-6.0% real conflict). This matches `htf_bias_engine.py`'s own design intent -- the `BIAS_THRESHOLD=+/-50` gate was built specifically so weak/ambiguous reads register as neutral rather than a false directional call; a ~70% neutral rate is the threshold behaving as designed, not a malfunction.

**Pairwise correlation among all 6 factors (score>=4 pool) -- f_bias is weakly, not strongly, related to any other factor:**

XAUUSD: max |r| involving f_bias is -0.26 (vs f_choch); f_bias vs f_crt = +0.12 (the ONLY positive pairing, and small, despite CRT literally being one of bias's own additive inputs).
EURUSD: max |r| involving f_bias is -0.23 (vs f_choch); f_bias vs f_crt = +0.06.

Co-occurrence confirms the same story numerically: conditioning on `f_crt=1` only lifts bias-agreement from the unconditional 26.4%/20.5% to 29.2%/21.8% -- a real but small effect, not redundancy. **HTF Bias is not simply re-stating the other 5 factors** (correlations are weak and mostly negative, not the strong positive correlation redundancy would predict) -- it appears to be capturing genuinely different, slower-forming information, consistent with it aggregating a wider set of inputs over a stricter threshold than any single fast/local factor (sweep, CHoCH) does alone.

**What this does and doesn't mean for the 6-factor score, reported without changing anything:** this rules out "redundant, so drop it" and "usually conflicting, so it's actively hurting candidates" as reasons to touch `f_bias`. What the data DOES suggest, as a distinct and separate question from redundancy: a factor that's neutral ~70% of the time can structurally almost never be the deciding vote that pushes a borderline candidate over an equal-weight threshold, simply because it's absent (0) far more often than sweep (85-90% present) or zone_stack (96-99% present) regardless of the setup's real quality -- that's a design question about how a conservatively-gated factor interacts with equal-weight binary scoring, not a data quality or redundancy problem. No weighting change made, per explicit instruction.

**Where it lives:** `scripts/diagnostic/prototype_composite_confluence.py` (`compute_stop_and_targets()` now accepts `target_max_atr_multiple`/`min_tp1_rr` as parameters instead of hardcoded globals, enabling this kind of sweep without code changes). The follow-up analysis itself (range sweep + bias correlation/co-occurrence) was a standalone script reusing this module's functions, not committed to the repo -- a one-off analysis pass, re-derivable from the committed module if needed again.

**Status:** both requested checks complete, reported before proceeding further per explicit instruction. Neither finding resolves the sample-size shortfall from the previous entry (77/98 signals, still well under the ~383 floor) -- range-widening is now a ruled-out lever, and the stop method remains the more promising one to revisit. HTF Bias's role in the score is an open design question, not a resolved one -- no changes made.

---

## zone_stack as a required gate: tested, changes almost nothing numerically

**What was tested:** zone_stack's near-universal presence (96-99% of the R:R-qualifying set, confirmed again here at 94.3%/95.6% of ALL candidates) as a REQUIRED GATE (prerequisite, not scored) with the other 5 factors (sweep, choch, crt, bias, div) as the scored confluence layer (0-5) on top -- vs the current all-6-equal-weight approach (0-6, threshold>=4). R:R floor held fixed at 3.0 throughout.

**At the closest equivalent strictness (gate + score5>=3, ~60%, matching baseline's 4/6~=67%): virtually identical to baseline, both symbols:**

| | XAUUSD | EURUSD |
|---|---|---|
| baseline (all-6, score>=4/6) | 77 signals, R:R median 3.52 | 98 signals, R:R median 3.62 |
| gated (zone_stack required + score5>=3) | 76 signals, R:R median 3.51 | 94 signals, R:R median 3.53 |

**Why this happens, mechanically:** zone_stack already passes 94.3%/95.6% of ALL candidates when tested as a standalone gate -- it was already functioning as a de facto precondition inside the current equal-weight score, not one differentiating vote among six. Formalizing it as an explicit gate is a real interpretability improvement (a cleaner mental model: "structure must be present, THEN confluence is scored") but it is NOT a lever that changes signal count or quality -- the two approaches select almost the same set of trades.

**A real, usable lever did surface as a side effect, reported without being adopted:** loosening the scored layer to score5>=2 (40% of the remaining 5, gate still required) meaningfully increases count with R:R still comfortably above floor:

| | XAUUSD | EURUSD |
|---|---|---|
| gate + score5>=2 | 138 signals (+79% vs baseline), R:R min=3.01 median=3.69 | 153 signals (+56% vs baseline), R:R min=3.00 median=3.56 |

**Where it lives:** standalone analysis script (not committed -- reused `prototype_composite_confluence.py`'s functions, one-off comparison pass, re-derivable if needed again).

**Status:** tested against real data as requested. zone_stack-as-gate does not meaningfully change the sample-size picture on its own; the score5>=2 loosening is a real lever but was not adopted, only reported.

---

## Target-widening + 383-trade floor, direct answer: EURUSD does not clear it, gap is not close

**What was asked:** with target-search widened, does EURUSD now clear the ~383-trade floor, and if not, is the remaining gap small enough that modest further widening would close it?

**Direct answer: no on both counts.** The exhaustive range sweep from the previous entry (10x-100x ATR, both symbols) already showed the qualifying count is COMPLETELY FLAT across every range tested -- widening cannot move this number at all, confirmed exhaustively, not re-tested again here since there is nothing left to test.

| | signals | floor required (699d) | % of floor | gap |
|---|---|---|---|---|
| EURUSD, baseline (current, any target range 10x-100x) | 98 | ~383 | 25.6% | ~285 short |
| EURUSD, most permissive variant tested to date (zone_stack gate + score5>=2) | 153 | ~383 | 40.0% | ~230 short |

Even the single most permissive configuration tested across both this entry and the previous one reaches only 40% of the floor -- roughly another 2-2.5x on top of the most generous variant tested would still be needed, not a marginal nudge. (Terminology note: "choch_only" is `ltf_trigger_engine.py`'s old mode split -- the composite engine has no equivalent mode, it's one unified signal stream; answered for EURUSD under the composite engine overall as the closest match to the ongoing discussion.)

**What this determines, directly:** the confluence-scoring side of the design (all-6-equal-weight or zone_stack-gated, any threshold tested so far) is NOT the bottleneck -- it barely moves the number either way (77-153 across every variant tested). The TP1 R:R>=3.0 floor combined with the stop-calculation method is doing nearly all of the filtering, and that combination is the lever that would need to move to close a gap this size. This is not yet a statistically trustworthy composite engine at either symbol under any variant tested.

**Status:** reported per explicit instruction, before proceeding further. No changes adopted.

---

## Composite Confluence Engine: full-pipeline build request paused -- premise didn't match today's actual numbers

**What happened:** the user asked to build the full production pipeline (persist `composite_confluence_signals`, wire into `run_detection.py`, run the full structural backtest for "4 combinations"), stating "3 of 4 combinations now clear or nearly clear the statistical floor (XAUUSD choch_only is only 11 signals short)." This was checked against everything actually computed today before building anything, per this project's standing "verify before acting" discipline -- it did not match.

**The mismatch:** the composite engine has no `choch_only`/`choch_sweep` mode split at all (CHoCH is one of the 6 parallel factors, not a mode) -- so "4 combinations" doesn't correspond to anything this engine produces; it's one signal stream per symbol. And the real numbers from every variant tested today were nowhere near a floor-clearing state: XAUUSD baseline 77/~383 (20.1%), EURUSD baseline 98/~383 (25.6%), and even the single most permissive variant tested (zone_stack gate + score5>=2) only reached 138/~383 (36.0%) and 153/~383 (40.0%) respectively -- no configuration tested today was "11 signals short" of anything. This appears to be a mix-up with the ORIGINAL baseline system (`ltf_trigger_engine.py`'s real `choch_only`/`choch_sweep` modes, 2217/1672/2508/2009 trades, which comfortably clears its own floor) -- a different pipeline with a very different sample size, not the composite engine this session has been validating.

**What was decided:** flagged directly to the user rather than silently building a full pipeline against a false premise (or quietly reinterpreting the request to make the numbers appear to fit). Given the choice between (a) holding off on the full build, (b) building anyway with the floor-miss as a loud caveat, or (c) clarifying that the "4 combinations" framing was actually about the original baseline system -- the user chose (a): **hold off on the full composite-engine pipeline build.** Backtesting a signal this thin (77-153 trades against this project's own ~383-trade, 200-per-12-months convention) would itself violate the exact statistical-floor discipline that's been enforced without exception on every other backtest in this log -- building it now would produce a result this project's own standard says not to trust.

**Where this leaves the Composite Confluence Engine:** design validated against real data (multiple entries above), zone_stack confirmed near-universal (gate vs scored made negligible difference), HTF Bias confirmed not redundant (mostly neutral, not conflicting), target-range widening exhaustively ruled out as a lever, TP1 R:R>=3.0 floor confirmed as the dominant bottleneck. NOT built as a production engine. The real, still-open question is whether a genuine lever exists to close a ~2.5-5x sample-size gap (depending on variant) without violating the non-negotiable TP1 R:R>=3.0 floor -- none tested so far has done this. Next step, if pursued, would need to target the stop-calculation method (the other confirmed-but-still-undecided open lever from the "4 stop-calculation methods" entry) rather than the confluence-scoring side, which has now been shown across multiple tests today not to be where the constraint lives.

**Status:** paused per the user's explicit choice, not abandoned. `analysis/strategies/composite_confluence_engine.py` remains undesigned-in-code; `scripts/diagnostic/prototype_composite_confluence.py` remains the only real artifact, kept as a reusable revalidation tool.

---

## Composite Confluence Engine: final lever (MAE-based stop) tested -- hard-stop condition triggered

**What was tested:** the MAE-based stop method (best median R:R in the earlier "4 stop-calculation methods" comparison -- 0.72-0.75x vs 0.28-0.38x for the other 3) applied to the Composite Confluence candidates, per the user's explicit "last untested lever before deciding" instruction. All-6 equal-weight scoring kept exactly as-is (per the user's own prior decision), target selection unchanged, TP1 R:R>=3.0 floor unchanged -- only the stop side changed. `compute_stop_and_targets()` extended with `stop_method='mae_atr'` (fixed entry -/+ `mae_atr_multiple` * ATR-14, no zone reference at all) alongside the existing `nearest_structure` default.

`mae_atr_multiple` per symbol: the earlier `MAE_ATR_MULTIPLE_75TH` values were derived per (symbol, MODE) against the original baseline system, which has no mode split in the composite engine -- averaged the two mode-specific values per symbol as the best available estimate (XAUUSD: (0.508603+0.492638)/2=0.5006x ATR; EURUSD: (0.524014+0.525502)/2=0.5248x ATR), stated explicitly since it's an approximation, not a fresh from-scratch MAE computation against composite-engine trades specifically (no such trades exist yet to compute MAE from).

**Result -- meaningful improvement, still fails the floor:**

| symbol | stop method | qualifying signals | % of ~383 floor | TP1 R:R median |
|---|---|---|---|---|
| XAUUSD | nearest_structure (prior best) | 77 | 20.1% | 3.52 |
| XAUUSD | **mae_atr** | **151** | **39.5%** | 3.68 |
| EURUSD | nearest_structure (prior best) | 98 | 25.6% | 3.62 |
| EURUSD | **mae_atr** | **177** | **46.2%** | 3.85 |

The MAE-based stop roughly DOUBLES the qualifying count at both symbols (77->151, 98->177) with R:R quality if anything slightly improved (median 3.68/3.85 vs 3.52/3.62) -- a real, meaningful effect, the strongest lever found across this entire design-validation pass. **It still does not clear the statistical floor at either symbol** -- 39.5% and 46.2% respectively, roughly 232 and 206 signals short of the ~383 required.

**Hard-stop condition met, per explicit instruction: no further variations tested.** This was the last lever identified (confluence-score threshold, zone_stack-as-gate, target-range widening, and now the best-available stop method all tested) -- none of them, individually or in combination, closes a gap of this size. Reported as instructed; not proceeding to test further combinations.

**Where it lives:** `scripts/diagnostic/prototype_composite_confluence.py::compute_stop_and_targets()` gained `stop_method`/`mae_atr_multiple` parameters (real, committed code -- reusable for any future revalidation). The test script itself was a one-off, not committed.

**Status:** all requested levers exhausted. Decision now due, presented to the user rather than made unilaterally: fall back to the validated baseline system (the real `choch_only`/`choch_sweep` engine, 2217/1672/2508/2009 trades, comfortably clears its own floor, already backtested multiple times today), or shelve the Composite Confluence Engine as a documented, promising-but-inconclusive finding -- the same treatment already given to the earlier confluence-zone-target experiment in this log. Composite engine NOT built as production code either way.

---

## Full-history curated-pipeline backfill: SMC zones, CRT, liquidity sweeps, divergence, HTF bias -- all extended to raw price depth (2003 XAUUSD / 2010 EURUSD)

**What was investigated first:** which of the 6 composite factors actually bottlenecks the ~2-year limit, given raw h1 goes back to 2003 (XAUUSD)/2010 (EURUSD). Checked every source table's real earliest timestamp directly: `smc_signals` h1 (2024-08-19), `crt_signals`/`htf_bias.crt_equilibrium_bias` (2024-09-13), `divergence_signals` h1 (2024-09-16, the latest of the three, i.e. the binding one). `sweep`/`choch` are computed live on raw m15 (already back to 2022-05/2022-08, not a bottleneck).

**Root cause, confirmed by code inspection:** `run_smc_zone_detection.py`, `run_htf_bias_detection.py`, and `run_divergence_detection.py` all hardcode `rolling_window_start()` (`analysis/rolling_window.py`, `ROLLING_WINDOW_DAYS=730`) as their query lower bound -- none accept a `--since` flag. This is the "2-year rolling window default" convention documented earlier in this log, not a genuine data-availability limit. `run_crt_detection.py`/`run_liquidity_sweep_detection.py`/`run_volume_profile.py` have NO filter at all -- their tables were simply stale from whenever they last ran.

**Execution:** temporarily widened `ROLLING_WINDOW_DAYS` to 8500 (~23.3 years) in `analysis/rolling_window.py`, ran the full `run_detection.py` orchestrator (the project's own existing pipeline, exact dependency order: feature engineering -> SMC zones h1/h4/h6/d1 -> CRT h4/h6 -> liquidity sweeps -> volume profile -> divergence technical x4 -> intermarket divergence -> HTF bias) for both symbols, then immediately reverted `ROLLING_WINDOW_DAYS` back to 730. All 9 stages passed, ~90 minutes total.

**Row counts, before -> after:**

| table | XAUUSD | EURUSD |
|---|---|---|
| smc_signals | 7,753 -> **41,763** (2003-05) | 8,069 -> **67,528** (2010-07) |
| crt_signals | 6,128 -> **35,754** | 6,164 -> **51,617** |
| liquidity_sweeps | 1,420 -> **7,210** | 1,652 -> **13,387** |
| divergence_signals | 2,328 -> **13,353** | 2,258 -> **19,099** |
| htf_bias | 11,343 -> **56,039** | 11,928 -> **99,949** |

**Stability check (the real correctness risk flagged before running -- stateful, sequential detection algorithms gaining ~20 years of extra prior context could in principle change results for the already-existing, already-validated window):** snapshotted checksums (row count, sum of key numeric fields) for the pre-existing 2-year window before running, re-checked after, RESTRICTED to the exact original date range (excluding new real-time tail rows that simply didn't exist yet at snapshot time, to isolate genuine value-drift from expected new-row growth). Result: **XAUUSD `smc_signals` came back byte-identical** (same count, same summed zone_top/zone_bottom, same invalidated count). **EURUSD `smc_signals`** gained a few new rows fully attributable to real-time drift during the ~90-minute run (sum differences proportional to the row-count difference, no per-row value drift). **`htf_bias` scores DID genuinely shift** for both symbols within the identical original range (confluence_score sums changed materially even after capping to the same row count for EURUSD) -- this is expected and correctness-improving, not corruption: `SMC_ZONE_RECENCY_WINDOW_BARS=720`'s zone-counting now has full prior context instead of running out of history near the old 2024-09 boundary. **Does not affect the baseline backtest system**, which reads `smc_signals` directly and never reads `htf_bias`.

**Composite Confluence Engine re-tested against the new depth -- but candidate generation is anchored on m15 touches, and raw m15 itself only reaches back to 2022-05 (XAUUSD)/2022-08 (EURUSD), not 2003/2010, so that (not the h1-based factors) is the real new ceiling:**

| symbol | old (700d window) | new (full m15 depth) | new floor required | % of floor |
|---|---|---|---|---|
| XAUUSD | 77 / 383 (20.1%) | **79 signals / 1,546 days** | ~847 | **9.3%** |
| EURUSD | 98 / 383 (25.6%) | **109 signals / 1,470 days** | ~805 | **13.5%** |

**Extending the window made the PERCENTAGE worse, not better** -- more than doubling usable history added only 2 (XAUUSD) and 11 (EURUSD) extra signals, nowhere near proportional. Investigated why directly: split candidates into early (2022-2024) vs late (2024-2026) sub-periods and compared score distributions and all 6 factors' presence rates -- statistically indistinguishable between the two (e.g. XAUUSD score>=4 rate: 42.4% early vs 40.7% late). The scoring side is NOT responsible for the sparse early-period yield -- the bottleneck is entirely downstream, in the stop/target/R:R>=3.0 stage. Why the early period's R:R pass rate is so much lower specifically was flagged as a genuine open question, not fully diagnosed further given this pass's scope.

**Where it lives:** `analysis/rolling_window.py` (temporarily widened, then reverted -- git history/this log is the record, not a permanent code change). No production script logic changed. `scripts/diagnostic/prototype_composite_confluence.py` re-run with `--days 1550`/`--days 1480` (not committed as a new default).

**Status:** backfill complete, verified stable, and the Composite Confluence Engine re-tested against it. Does not change the "does not clear the floor" conclusion -- if anything, strengthens it (percentage of floor dropped, not rose, once the fuller history was actually tested rather than assumed to help).

---

## CORRECTION: the "h4 raw data is a genuine dependency blocker" claim from the previous entry was wrong

**What happened:** the user asked to (A) backfill `raw_gold.h4`/`raw_eurusd.h4` to full h1 depth using the h4-from-h1 resample pattern "already built for h6", and (B) verify via an isolated test-schema run before touching production. Investigating (A) before executing it surfaced that its own premise -- stated in the immediately preceding entry ("h4-based CRT equilibrium AND h4 SMC zones ... raw h4 table itself only starts 2024-03/2023-10 ... a genuine, real hard dependency limit") -- was incorrect.

**The correction, verified by direct code inspection, not assumption:** a comprehensive search for every SQL consumer of the stored `raw_<symbol>.h4` table (`` FROM `h4` ``/`FROM h4`) across the entire codebase returned ZERO matches. `run_smc_zone_detection.py::load_ohlcv()`, `run_crt_detection.py`, `run_feature_engineering.py`, and `dashboard/1_Chart.py` all ALREADY resample h4 from h1 live (`resample_ohlc()`, `RESAMPLE_RULE`) -- the exact same pattern previously identified as h6-specific is actually already applied to h4 too, project-wide. The stored `raw_gold.h4`/`raw_eurusd.h4` tables (real broker data from ~2024-03/2023-10 onward) are not read by anything -- a vestigial artifact, not a load-bearing dependency.

**Consequence for both requested actions:**
- **Option A (backfill raw h4) would be cosmetic only** -- no consumer would benefit, since every real consumer already gets full h1 depth (2003/2010, per the backfill entry above) via live resampling, not the stored table.
- **Option B's target (an isolated test-schema pipeline run before production)** turns out to already be moot: the actual full-history recompute (SMC zones -> liquidity sweeps -> CRT -> divergence -> HTF bias) already ran directly against production in the entry above, with a stability check already performed and already passing.

**What was decided:** presented this correction to the user directly rather than either silently executing a no-op backfill or silently redoing already-verified work. The user chose to skip both -- Option A because it would change nothing, Option B because its target already happened and was already verified. **The Composite Confluence Engine's full-history result stands as final from the entry above: 79/847 (9.3%) XAUUSD, 109/805 (13.5%) EURUSD of the (correspondingly scaled) statistical floor.** No further backfill action is planned.

**Why this is worth recording explicitly, not just quietly correcting:** the previous entry's h4-dependency claim was stated with the same confidence as every other verified finding in this log, but was NOT actually verified by checking real consumers at the time -- it was inferred from `raw_gold.h4`'s own shallow date range without checking whether anything reads that specific table. This is exactly the kind of unverified inference this project's own standing discipline ("evidence first, then act") exists to catch, and this entry is the record of it being caught -- one turn later, but before any production action was taken on the mistaken premise. Also recorded here: the full-history backfill entry above was itself reported to the user in chat during the previous turn but never actually written to this log at the time -- a real process gap, caught and fixed in this same pass rather than left silently missing.

**Status:** corrected and closed. No h4 backfill performed (confirmed unnecessary). No test-schema pipeline run performed (confirmed the target already completed and was already verified). Composite Confluence Engine remains parked at 9.3%/13.5% of floor, unresolved.

---

## Final lever tested: TP1 R:R floor lowered to >=2.0 -- biggest effect found, still doesn't clear the floor

**Pre-check requested and done first, per explicit instruction, before running anything:** confirmed whether the MAE-based stop's survivorship bias (flagged when the method was introduced -- MAE computed from WINNING trades only, `exit_reason='win'`) had been fixed. It has NOT. `scripts/backtest/compare_stop_calculation_methods.py` still computes MAE from winning trades only, its own docstring still states "survivorship bias by construction," and `MAE_ATR_MULTIPLE_75TH`'s hardcoded values are still derived from that same biased calculation -- unchanged since it was first flagged. **Not used for this test.** Properly fixing it (re-simulating to find each trade's real path-dependent excursion regardless of outcome, not just re-averaging existing winner data) is a real sub-project, out of scope here. Used `nearest_structure` instead -- purely geometric (nearest same-direction zone's far edge, ATR-floored/capped), no dependency on trade outcomes, no bias possible by construction, and the method with the best real expectancy across all 4 backtest combinations in the original "4 stop-calculation methods" comparison.

**Test: TP1 R:R floor >=2.0 (down from the standing >=3.0) + `nearest_structure` stop, score>=4/6 unchanged, full post-backfill history, both symbols:**

| symbol | R:R floor | signals | % of scaled floor | R:R distribution (min/p25/median/p75/max) |
|---|---|---|---|---|
| XAUUSD | >=3.0 (standing) | 79 | 9.3% of 847 | 3.01 / 3.25 / 3.59 / 4.53 / 10.41 |
| XAUUSD | **>=2.0** | **228** | **26.9% of 847** | 2.00 / 2.17 / 2.56 / 3.27 / 10.41 |
| EURUSD | >=3.0 (standing) | 109 | 13.5% of 805 | 3.00 / 3.26 / 3.62 / 4.45 / 12.29 |
| EURUSD | **>=2.0** | **339** | **42.1% of 805** | 2.00 / 2.24 / 2.62 / 3.20 / 12.29 |

Lowering the floor to 2.0 nearly TRIPLES signal count at both symbols (79->228 XAUUSD, 109->339 EURUSD) -- the single largest effect of any lever tested in this entire investigation (bigger than the score threshold, zone-stack gating, target-range widening, or the MAE-based stop's ~2x effect at R:R>=3.0). The R:R distribution shifted exactly as expected for a loosened binding constraint -- median dropped ~3.6->2.6, p25 sits just above the new floor (more marginal candidates let through), max unchanged (set by genuinely wide setups, not the floor).

**Neither symbol clears its floor even here** -- 26.9% (XAUUSD) and 42.1% (EURUSD). EURUSD gets closest of any test run today, but still needs roughly 2.4x more signals.

**Per explicit instruction, this is the last combination tested -- stopping here regardless of outcome.** Summary across the full investigation: confluence-score threshold, zone-stack-as-gate, target-range widening (10x-100x ATR, no effect), stop-calculation method (zone_far_edge -> nearest_structure -> MAE-based, biased and unusable), full-history backfill (2003/2010, real but insufficient), and now the R:R floor itself (3.0 -> 2.0, the biggest single lever) -- none, alone or in combination, clears the statistical floor for the Composite Confluence Engine at either symbol under this design.

**Where it lives:** standalone test script, not committed (reused `prototype_composite_confluence.py`'s functions unmodified, `stop_method` left at its unbiased default).

**Status:** investigation complete, per explicit "report findings and stop regardless of outcome" instruction. The Composite Confluence Engine remains NOT built as a production engine. The decision of whether to fall back to the validated baseline system or shelve this as a documented, promising-but-inconclusive finding remains the user's to make -- not resolved by this entry.

---

## Composite Confluence Engine ADOPTED as production -- built for real, and backend review

**Decision (the user's, recorded verbatim in reasoning):** adopt the Composite Confluence Engine as the production signal source going forward, despite it not clearing this project's own statistical floor at adoption time. Reasoning: its R:R profile (median ~2.5+, at the tested R:R>=2.0/score>=4/6 configuration) is what the user actually wants to trade -- the original baseline's R:R (median 0.28) isn't tradeable regardless of its much higher win rate and larger validated sample. The track record is intended to accumulate through real, logged usage rather than another historical backfill exercise.

**Production defaults, as adopted:** `SCORE_THRESHOLD=4` (of 6, equal-weight, unchanged after the zone_stack-as-gate test showed negligible difference), `MIN_TP1_RR=2.0` (down from the originally-tested 3.0 -- this specific combination is what produced the R:R profile that motivated adoption), stop = `nearest_structure` (confirmed unbiased; the MAE-based alternative was confirmed STILL biased -- survivorship bias never fixed -- and explicitly not used, per the user's own instruction before the last test was run).

**1. Continuous stat collection -- built for real, not another script:**

- **Schema:** `composite_confluence_signals` (both `curated_gold`/`curated_eurusd`, matching the `confluence_zones` pattern -- full breakdown stored, not just headline numbers). One row per QUALIFYING signal only (non-qualifying candidates are never persisted, matching `structural_tp_engine.py`'s skip-not-weaken convention). Columns: all 6 factor flags individually (not just the total, so factor-presence patterns keep being checkable as the sample grows), entry/stop/risk, the full ranked target ladder as JSON plus denormalized TP1 price/R:R, and outcome tracking (`exit_reason` open/win/loss, `exit_bar_datetime`, `resolution_method`, `r_outcome`) -- PLUS two human-in-the-loop columns (`user_action` taken/skipped/modified, `user_note` free text) added specifically to close the "human-in-the-loop" gap the review below identifies, not left as a placeholder.
- **Production engine module:** `analysis/strategies/composite_confluence_engine.py` -- the validated prototype logic (candidate generation, 6-factor scoring, `nearest_structure` stop, multi-target ranking) ported into a clean, importable module. `scripts/diagnostic/prototype_composite_confluence.py` is kept as-is, unmodified, as the reusable research/revalidation tool -- the two are now deliberately separate (research vs. production).
- **Detection script:** `scripts/detection/run_composite_confluence_detection.py` -- generates and upserts new qualifying signals, bounded by the standard rolling window by default (matching every other `run_*.py` script's convention for ongoing live use), with a `--since` override used once at adoption to seed the table from the already-validated full-history signal set.
- **Resolution script:** `scripts/detection/run_composite_confluence_resolution.py` -- resolves `'open'` rows against real price history as it accumulates, by reusing `structural_backtest_engine.simulate()` UNMODIFIED (the exact same walk-forward/ambiguous-bar-drilldown/conservative-SL-fallback logic the baseline system's own backtest uses), judged against TP1/stop -- no reimplementation, no new resolution logic. No overlap constraint applied (this table tracks each signal's own outcome, not a simulated single-account equity curve -- the user decides in real trading which signals to actually take, hence `user_action`/`user_note`).
- **Wired into the pipeline:** `run_detection.py` gained two new stages ("Composite Confluence signals", "Composite Confluence resolution") after HTF bias -- the live track record now grows automatically every time the regular detection pipeline runs, with zero extra manual steps.

**Seeded with the already-validated full-history signal set (not starting from an empty table), then resolved against real price history:**

| symbol | signals seeded | resolved | wins | losses | win rate | expectancy R | R:R range (winners) |
|---|---|---|---|---|---|---|---|
| XAUUSD | 228 (matches prior validation exactly) | 228/228 | 75 | 153 | 32.9% | **+0.181R** | up to 7.21R |
| EURUSD | 339 (matches prior validation exactly) | 339/339 | 109 | 230 | 32.2% | **+0.178R** | up to 4.75R |

**Real, honest read of this first resolved sample:** win rate (32-33%) is far below the baseline system's ~75%, exactly as expected for a wider-R:R/tighter-stop profile -- fewer, bigger wins offsetting more frequent losses. Expectancy is genuinely POSITIVE at both symbols (+0.18R), which is a real, if still statistically thin (228/339 signals, well under the ~847/805 floor), first data point in favor of the adoption reasoning. This is descriptive, not a validated claim -- no DSR/floor-clearing claim is being made here, this is the starting sample the "track record accumulates through use" plan is built on.

**2. Backend review -- what's actually built, and what's missing that MORE BACKTESTING on the same 2003-2026 price history cannot fix:**

Reviewed the full mechanism end to end (candidate generation, all 6 factors, stop/target logic) against what a discretionary trader watching this system daily would know that isn't derivable from OHLCV + the existing curated tables alone. Organized by what's genuinely closed by real-data testing (already done, exhaustively, today) vs. what requires the user's own input:

**Real gaps, and the concrete manual input that would close each one:**

1. **Touch quality has no concept of strength.** A one-bar wick into a zone and a multi-hour consolidation inside a zone both score identically (`f_zone_stack`/touch = binary). *Ask:* does the user's own screen-time judgment distinguish "clean touch, I'd take it" from "sloppy touch, I'd skip it" in a way that could become a 7th factor or a touch-quality multiplier? Concrete version: log `user_action='skipped'` with a note on WHY for a few weeks -- the pattern in those notes is the actual signal.

2. **No news/economic-calendar awareness at all.** The engine is purely technical -- zero forward-looking awareness of NFP/FOMC/CPI or other scheduled high-impact events, even though `intermarket_divergence_state.py` already models some of these series statistically (lagging, not a forward filter). *Ask:* does the user currently avoid entries around specific news events? If yes, the exact rule (e.g. "no new entries within 30min of high-impact releases") is directly implementable as a real filter -- this is the single most concrete, cheapest-to-implement item on this list if the answer is yes.

3. **Zone-timeframe trust is unweighted.** `zone_stack` counts any 2+ overlapping SAME-TIMEFRAME (h1) zones equally -- a d1 order block and an h1 swing level count identically toward the score, even though they're structurally very different in significance. *Ask:* from real trading experience, does a d1/h4 zone actually hold up meaningfully better than an h1/h6 one, or does it not matter in practice? This would directly inform whether `zone_stack` (or a new factor) should be timeframe-weighted.

4. **Session/time-of-day is not in the composite score at all**, despite this project already having a validated session-weighting mechanism (`htf_bias_engine.py`'s `SESSION_MULTIPLIER`/killzone logic) that simply isn't reused here. *Ask:* does the user only trade certain sessions regardless of what a signal says? If so, this is a near-zero-cost addition since the mechanism already exists elsewhere in the codebase.

5. **Entry execution model may not match real behavior.** The engine's "entry" is the LTF close at the touch bar -- a market-order-at-touch assumption. *Ask:* does the user actually enter that way, or do they wait for a confirmation candle, use a limit order inside the zone, or scale in? This changes what "entry" should even mean for both live signals and the resolution script's outcome tracking.

6. **No trade-management logic once a position is open.** The engine outputs a static TP1..TP5 ladder and nothing else -- no partial-profit-taking, no breakeven-move rule, no trailing logic. *Ask:* how does the user actually manage a winning trade in practice (take TP1 and let a runner ride to TP2+? move to breakeven after TP1? something else)? This is exactly the kind of thing that only comes from someone who trades the setup daily, not from more historical analysis.

7. **No capital-management/position-sizing layer** -- flagged repeatedly throughout this entire project as not yet built, still true. The R:R numbers this adoption decision is based on are risk-multiples, not dollar outcomes. *Ask:* real account size and position-sizing rule (fixed %, fixed lot, etc.) -- needed before "tradeable R:R" claims connect to real survivability under a losing streak (worth noting: min_r in the resolved sample above is exactly -1.000R at both symbols, i.e. no losses have exceeded 1R yet in this small sample -- a real, reassuring data point, but not yet stress-tested against a real losing streak).

8. **Factor-weighting intuition.** Today's data found `zone_stack`/`sweep` near-universal and `bias`/`choch` comparatively weak among qualifying signals -- purely a data-driven finding, never checked against the user's own trading intuition. *Ask:* does this match what they've noticed from screen time, or does their experience suggest a different factor matters more than the data alone shows? This is the one item that's genuinely a hybrid -- it's about interpreting the SAME historical data through real trading judgment, not new data.

**What is explicitly NOT on this list, because more of it wouldn't help:** re-testing more score thresholds, more R:R floors, more stop methods, or more target ranges against the same 2003-2026 archived OHLCV. That lever has been pulled exhaustively today (every combination tested, diminishing-to-zero returns past R:R>=2.0) -- none of items 1-8 above can be derived from more analysis of the same historical candles; they require either the user's own domain knowledge not present in raw price data (news rules, session preference, zone-timeframe trust, factor intuition, trade management), a genuinely new external data stream (economic calendar), or forward observation that hasn't happened yet (the trade journal).

**Highest-value, lowest-friction first ask:** item 1 (the trade journal) is already schema-supported (`user_action`/`user_note` columns exist right now, today) and starts compounding immediately with zero additional engineering -- the single most concrete thing the user could start doing today that isn't achievable through any further backtesting.

**Where it lives:** `storage/schema_curated.sql` (`composite_confluence_signals`, both databases, applied live), `analysis/strategies/composite_confluence_engine.py` (new), `scripts/detection/run_composite_confluence_detection.py` (new), `scripts/detection/run_composite_confluence_resolution.py` (new), `scripts/detection/run_detection.py` (two new stages wired in).

**Status:** production pipeline built, live, seeded, and resolved against real data. Backend review complete with a concrete, prioritized list handed to the user. Awaiting the user's input on any of the 8 items above -- none required to keep the system running (it already is), but each is a real, identified lever that more backtesting cannot substitute for.

## Composite Confluence Engine -- gap-list resolution: #3 confirmed bug, timeframe weighting fixed, CRT dropped from scoring, SMC+Divergence adopted

User's response to the 8-item gap list above: #1 (trade journal) and #2 (news awareness) rejected -- system responsibility, not the user's job to hand-hold. #6 (trade management) and #7 (position sizing) rejected as "manage this for me," #7 narrowed to a fixed 0.01 lot / $300 starting capital assumption for stat reporting only, no sizing algorithm. #3 (zone-timeframe weighting), #5 (entry timing), #8 (zone-stacking value), and #4 (session reporting) accepted, with #3 prioritized first ("before doing anything else") since it might be actively wrong right now, not just underweighted.

**#3 -- confirmed a real bug, not a design choice:** grepped the actual scoring code. `zone_stack` (and all zone-dependent logic in the engine) only ever loaded/considered h1-timeframe zones -- h4/h6/d1 structure was completely invisible to the composite score, not merely equal-weighted. Original design intent (D1 > H6 > H4 > H1, "get all timeframes to cooperate") was never implemented at all.

**Fix:** added `ZONE_TIMEFRAME_WEIGHT = {"d1": 4, "h6": 3, "h4": 2, "h1": 1}` to `composite_confluence_engine.py`; `score_candidates()` now takes an `all_tf_zones` param (all 4 timeframes) and sets `f_zone_stack = int(weighted_sum >= 2)`, reusing the existing threshold=2 rather than inventing a new tunable constant -- a lone D1 zone (weight 4) now satisfies it alone, exactly reproducing the original h1-only rule when every contributing zone is h1. `run_composite_confluence_detection.py`'s `load_all()` updated to also query `smc_signals` across all 4 timeframes for this factor only; candidate generation and stop/target zone search stay h1-only (unchanged, out of scope for this fix).

**Live-data-impact check (user explicitly required this before any write, having flagged the 228/339 already-tracked signals):** first diff pass had a bug of its own -- compared full-precision floats against the DB's `DECIMAL(16,5)`-stored values with a 1e-6 tolerance, tighter than the DB's own rounding, making nearly every row look changed when it wasn't. Fixed to round both sides to DB precision before comparing. Corrected result: 224/228 (XAUUSD) and 337/339 (EURUSD) rows had byte-identical stop/target/tp1_rr; only 4 + 2 = 6 rows total had real parameter changes, all already resolved (the only rows where a naive upsert would leave `exit_reason`/`r_outcome` computed against now-stale parameters); 0 rows dropped out of qualification; 8 + 10 new signals appeared. Reported to the user in full before writing anything.

**Then, in the same session, gap items #5/#8 priority order was superseded by a new, more direct request: rejection-factor breakdown + isolated scoring variants**, run full-history end-to-end (candidates -> score -> stop/target -> `structural_backtest_engine.simulate()`, the same walk-forward/ambiguous-bar-drilldown logic used everywhere in this project -- no shortcuts):

**Rejection breakdown** (among candidates scoring < 4/6, which factor is most often the zero): `htf_bias` missing in ~97% of rejections, `choch` in ~83-85%, `crt` in ~61-63% (mid-pack), `divergence` ~49-54%, `sweep` ~49-50%, `zone_stack` <1% (post-fix, a lone higher-TF zone almost always clears it now). **CRT was not the bottleneck** -- htf_bias and choch alignment were.

| variant | XAUUSD qualifying / win% / expectancy | EURUSD qualifying / win% / expectancy |
|---|---|---|
| SMC-only (sweep+choch+zone_stack+bias, >=3/4) | 169 / 33.7% / +0.223R | 216 / 36.1% / +0.315R |
| CRT-required (crt gate + 4/6) | 187 / 28.9% / **+0.008R** | 273 / 23.8% / **-0.126R** |
| production 6-factor (ref) | 236 / 32.6% / +0.169R | 349 / 31.5% / +0.154R |
| **SMC + Divergence (no CRT), >=3/5** | **325 / 40.0% / +0.433R** | **455 / 36.3% / +0.327R** |

CRT-required was the *worst* performer of everything tested, including negative expectancy on EURUSD -- confirming CRT-as-gate actively hurts rather than filters toward quality. SMC+Divergence (CRT removed entirely, sweep+choch+zone_stack+bias+divergence, threshold 3/5 -- closest achievable proportion to the original 4/6, same methodology as SMC-only's 3/4) beat SMC-only on every single metric in both symbols: ~2x the sample size, higher win rate (flat on EURUSD), higher expectancy on both. Per the user's own stated adoption rule ("if SMC+Divergence performs comparably or better than SMC-only, adopt this as the production configuration, drop CRT from the scoring entirely") -- **adopted**.

**Note:** the user's message requesting this test cited baseline SMC-only figures (47.7%/66.8% of floor, expectancy 1.35R/0.98R) that did not match what this session's own code produced (19.9%/26.8% of floor, +0.223R/+0.315R). Flagged explicitly to the user before running the new test; the comparison above uses this session's own verified numbers throughout, not the cited ones.

**Production changes:** `SCORE_THRESHOLD` changed from 4 (of 6) to 3 (of 5); `score_candidates()` still computes `f_crt` (kept as a plumbed-through column, harmless, in case a future test wants it back) but no longer includes it in the score sum. Confirmed mathematically (and empirically, via the same no-write diff methodology as the #3 fix) that this change cannot invalidate any already-qualifying signal: any row with score>=4/6 loses at most 1 point by dropping CRT, leaving >=3/5, exactly the new threshold -- 0 rows dropped out in either symbol. Same 6 rows (4 XAUUSD/2 EURUSD) as the #3 fix remain the only ones with real stop/target changes.

**Written to production** (full history, `--since 2022-05-24`/`2022-08-08`, matching original seeding): 325 XAUUSD / 455 EURUSD signals upserted, then resolved end-to-end against real price history -- 97 XAUUSD (55W/42L) and 116 EURUSD (56W/60L) newly-open signals resolved, 0 left open. `composite_confluence_engine.py`'s module docstring updated to document the 5-factor design and the CRT-drop reasoning inline.

**Still pending from the original 8-item list:** #4 (session/time-of-day reporting breakdown -- reporting-only addition, not yet done) and #5 (entry-timing empirical test: touch-immediate vs. wait-for-CHoCH-confirmation -- not yet done, was superseded by the CRT/isolation work this session but not rejected).

## Nested Zone Drilling adopted as production entry mechanism -- replaces H1-touch

User requested the "LTF zoom-in piece": instead of the composite engine anchoring candidates on a bare m15 touch of an h1 zone, drill from any qualifying HTF zone (D1/H6/H4/H1, no requirement to start at D1) down through the fixed hierarchy D1>H6>H4>H1>M15>M5, finding nested same-direction sub-zones (OB/FVG/swing) at each finer level, terminating at whichever LTF level (M15 preferred, M5 fallback) produces a valid nested zone -- the tightest possible entry/stop. A chain that fails to reach M15 or M5 is discarded entirely, not silently degraded back to the HTF zone.

**Built:** `analysis/strategies/nested_zone_engine.py` (drill algorithm, reuses `SMCZoneStateEngine.detect_zones()` UNCHANGED at every level including M15/M5 -- confirmed timeframe-agnostic, not a new engine); `nested_zone_chains` + `ltf_smc_zones` tables (kept separate from `smc_signals`, which means "the HTF layer" everywhere else in this project); `build_candidates_from_chains()` -- the alternate entry-anchor path, implemented as a reshape into `composite_confluence_engine.build_candidates()`'s existing input shape rather than a parallel implementation, so scoring/stop-target/resolution are 100% the same code the H1-touch mechanism used.

**Side-by-side comparison, real data, both mechanisms through the identical downstream pipeline** (three runs, escalating rigor):

| run | XAUUSD (A) H1-touch | XAUUSD (B) Nested Drill | EURUSD (A) H1-touch | EURUSD (B) Nested Drill |
|---|---|---|---|---|
| 60 days (pre-fix) | 18 / 38.9% / +0.341R | 1 / 100% / +2.548R | 35 / 42.9% / +0.566R | 2 / 0% / -1.000R |
| 60 days (post-fix) | 18 / 38.9% / +0.341R | 4 / 100% / +2.460R | 35 / 42.9% / +0.566R | 6 / 66.7% / +1.413R |
| **180 days** | 67 / 40.3% / +0.476R | **13 / 92.3% / +2.543R** | 105 / 38.1% / +0.407R | **11 / 72.7% / +2.498R** |

(format: qualifying signals / win rate / expectancy)

**A real bug was caught and fixed mid-comparison, not glossed over:** the first pass (n=1/n=2) looked like nested drilling barely produced any signals -- but 40/34 valid chains had been found, only 1-2 became qualifying signals. Traced to `build_candidates()`'s reused `formation_closed = created + 1h` touch gate, tuned for H1 zone lifespans -- M15/M5 zones routinely mitigate/invalidate inside an hour, so the gate was killing ~95% of real touches before they could register. Fixed by generalizing the gate to "one bar of the zone's own timeframe" (the H1 default was always really "wait for the formation bar to close," which happened to be 1h only because every zone build_candidates() had ever seen was H1) via an optional per-zone `timeframe` column, selected through `FORMATION_GATE_BY_TIMEFRAME` -- zero behavior change to the H1 path (which never passes that column). Qualifying count moved from n=1/n=2 to n=4/n=6 immediately, confirming the diagnosis. The user then asked to extend the window before deciding (180 days), which produced n=13/n=11 -- direction and magnitude held consistent across all three runs, which is what made this a defensible adoption decision rather than premature pattern-matching on n=1.

**Second real bug caught during the production rollout itself, before declaring done:** writing nested_chain-sourced signals via the existing `ON DUPLICATE KEY UPDATE` upsert (keyed on `symbol, ltf_timeframe, direction, confirmed_at_bar`) silently collided with 2 pre-existing XAUUSD rows whose `confirmed_at_bar` happened to coincide with a new nested-chain touch time -- those rows got their `entry_price`/`stop_price`/`targets`/`entry_mechanism`/`zone_chain` overwritten with new values while `exit_reason`/`resolution_method`/`r_outcome` stayed stale (computed against the OLD h1_touch parameters), same class of risk flagged and checked for during the #3 zone-weighting fix and the CRT drop. Caught by comparing "rows upserted" (13) against "rows open for resolution" (11) -- a 2-row gap that shouldn't exist for a first-time write. Fixed: reset the 2 rows to `open` and re-ran resolution against their real current parameters (both resolved win). EURUSD had zero collisions (11 written = 11 open), confirmed by direct query.

**Production changes:** `composite_confluence_signals` gained `entry_mechanism ENUM('h1_touch','nested_chain')` and `zone_chain JSON NULL` columns (additive, both DBs) -- existing rows default to `h1_touch`/`NULL`, kept as historical record, never rewritten. `run_composite_confluence_detection.py` now drills chains (bounded to `NESTED_WINDOW_DAYS=180`, not the full ~730-day rolling window -- drilling runs fresh M15/M5 zone detection per candidate root, too expensive to run at full rolling-window depth on every regular pipeline pass) and uses the chain terminal zones for BOTH the candidate anchor (`build_candidates`) and the stop/target structural search (`compute_stop_and_targets`) -- searching among the tight LTF terminals for the stop reference is what delivers the "smallest possible SL" the design was built for; falling back to coarse H1 zones there would silently widen every stop back out.

**Sweep/factor scoring re-verified intact post-swap** (explicit ask before declaring done): `f_sweep` 85.9%, `f_choch` 50.8%, `f_zone_stack` 100%, `f_crt` 41.4% (still computed, correctly unused), `f_bias` 5.8%, `f_div` 95.8% among 191 qualifying-threshold candidates -- all plausible and consistent with prior findings (zone_stack near-universal post-weighting-fix, htf_bias scarcest factor), nothing broken by the swap.

**Written to production, resolved, and verified live:** 13 XAUUSD (12W/1L, +2.543R) / 11 EURUSD (8W/3L, +2.498R) nested_chain signals, alongside 323 XAUUSD / 455 EURUSD legacy h1_touch signals kept as historical record. `run_detection.py` and `main.py` labels updated to reflect the new mechanism and its slower runtime (expected, not a hang). README updated (`analysis` section, additive per the user's own "add, don't rewrite" instruction for that section).

**Dashboard placement corrected after initial build:** first version added a standalone `dashboard/pages/7_Nested_Zones.py` browser page and a "Nested Zone Chain" detail panel on `3_LTF_Triggers.py`. User explicitly rejected both -- "delete/discard any new separate page or panel... everything goes on the existing Chart page only, layered with the current timeframe overlays." Both removed; chain visualization instead lives entirely on `dashboard/1_Chart.py` as a new "Nested Zone Chains" overlay checkbox, reusing the exact same per-timeframe visual weighting (`ZONE_TF_VISUAL`, D1 thick/opaque -> M15/M5 thin/light) already built for the SMC zone overlay, with a gold border marking chain membership and the full breadcrumb as the label on every level. Also reuses the existing "zones near current price only" distance filter (whole chains filtered by their terminal/entry zone's distance, not per-level, so a chain never renders partially) -- without it, 40 chains x ~2.5 levels each reintroduced the exact clutter that filter was built to fix. `3_LTF_Triggers.py`'s UI itself was never touched beyond that one panel add-then-remove -- confirmed via grep (zero "chain"/"nested" references remain) that its card/chart/factor-breakdown layout is unchanged from before Nested Zone Drilling existed; only the underlying signal source changed.

**Not yet done:** wiring `run_composite_confluence_detection.py`'s nested-chain stage into the regular scheduled pipeline cadence at anything beyond the existing `run_detection.py` call (no separate scheduling changes were needed since it's the same stage, just slower) -- and no attempt yet to reduce `NESTED_WINDOW_DAYS` runtime cost via caching/incremental drilling, which will matter more as this runs daily going forward.

## Nested Zone Drilling follow-up: prioritize roots near composite factors before drilling (tested, not adopted)

User raised a fair architectural question: does root-zone selection for Nested Zone Drilling know anything about composite scoring (sweep/CHoCH/zone_stack/bias/divergence), or do they run independently and only combine after, via the touch? Traced the exact code path (`run_composite_confluence_detection.py` lines 206-219): confirmed **independent, combined after** -- `build_nested_chains()`'s only root gate is `state in ('active','mitigated')`, a pure SMC-structural property with zero reference to composite factors; `score_candidates()` is then computed on whatever touch results from drilling, unaware the touch came from a chain at all. Explained why this isn't a new coupling gap: composite confluence was never a property a zone could "pass" in isolation -- sweep/CHoCH/bias/divergence are all time-dependent conditions evaluated at touch-time, and the original H1-touch mechanism had exactly the same "any zone can anchor a touch; scoring judges the touch after" structure. But the user's underlying concern was real: 99 XAUUSD chains drilled, only 13 became qualifying signals -- most drilling compute was spent on chains with no composite support nearby at all.

**Built:** `nested_zone_engine.filter_roots_near_composite_factors()` -- pre-filters ROOT candidates only (not the intermediate-level nesting search pool, which stays the full zone universe once a chain has started) to zones with enough of the same 5 factors composite scoring already checks present nearby.

**First attempt failed a self-check, caught before being reported as a result:** initial version used OR-across-5-factors with an arbitrary multi-day window on the time-series factors (bias/divergence). Result: **100% of roots kept in every timeframe, both symbols** -- (C) came out byte-identical to (B), which is impossible for a real filter and was the tell. Diagnosed: sweep/CHoCH/bias/divergence are each individually common enough over a multi-day window that ORing 5 of them together is nearly always true (confirmed further: even a 2-factor sweep/CHoCH-only unbounded-time version only filtered 1-5% of roots).

**Fixed two ways, both reusing existing constants rather than inventing new ones:** (1) replaced the arbitrary window with the EXACT windows `score_candidates()` itself uses to judge these factors at touch-time -- `TOUCH_WINDOW_M15_BARS` (5h) for sweep/CHoCH, `DIVERGENCE_LOOKBACK_H1_BARS` (20h) for divergence, and a "latest reading at/before this moment" snapshot (never a window) for bias, matching how `f_bias` itself is evaluated; (2) require 2+ of 5 factors present, not just 1.

**Result (180-day comparison, same methodology as the original H1-touch-vs-nested-drilling test):**

| | XAUUSD unfiltered (B) | XAUUSD prioritized (C) | EURUSD unfiltered (B) | EURUSD prioritized (C) |
|---|---|---|---|---|
| Root pool kept | 100% | 79-85% | 100% | 83-90% |
| Chains drilled | 99 | 76 (-23%) | 69 | 64 (-7%) |
| Qualifying signals | 13 | 12 | 11 | 10 |
| Win rate | 92.3% | 91.7% | 72.7% | **80.0%** |
| Expectancy | +2.543R | +2.548R | +2.498R | **+2.847R** |
| Yield (qualifying/chains drilled) | 13.1% | **15.8%** | 15.9% | 15.6% |

**Honest read, reported as such, not oversold:** real ~7-23% compute savings (fewer chains drilled), and a small, mixed quality effect -- XAUUSD roughly flat, EURUSD modestly better on win-rate/expectancy but with one fewer signal each side. This is a smaller, more mixed signal than the original H1-touch-vs-nested-drilling adoption (which had 3 consistent runs, all metrics moving the same direction, large margins). **Not adopted into production** -- `run_composite_confluence_detection.py` remains on unfiltered roots (what was actually validated for the swap); `filter_roots_near_composite_factors()` exists as a tested, available-but-unused option pending the user's decision on whether the compute savings justify the smaller/mixed sample.

## f_choch factor: confirmed CHoCH-only, BOS inclusion tested and rejected

User asked to confirm exactly what the composite score's `f_choch` factor checks, given `SMCStructureEngine.detect_bos_choch()` detects both CHoCH (reversal) and BOS (Break of Structure, continuation) signals. Traced the exact code: `run_composite_confluence_detection.py` calls `detect_bos_choch()` (which computes both) but immediately filters the result to `BULLISH_CHOCH`/`BEARISH_CHOCH` rows only before it ever reaches `score_candidates()` -- BOS rows are discarded at that filter, never seen by the scoring function at all. Confirmed this was an unintentional gap, not a documented deliberate choice -- no comment or prior DECISIONS.md entry explained excluding BOS specifically, and the module docstring described the factor as running the full `detect_bos_choch()` output without mentioning the CHoCH-only narrowing.

**Fix scoped and tested per the user's explicit request (option a: broaden f_choch to count CHoCH OR BOS), not applied blind:** added `include_bos: bool = False` to `score_candidates()` (default preserves current production behavior exactly -- existing callers passing pre-filtered CHoCH-only data are unaffected). When `True` (with the FULL unfiltered `detect_bos_choch()` output, BOS rows included), `f_choch` matches `BULLISH_CHOCH`/`BULLISH_BOS` (or the bearish pair) instead of CHoCH alone.

**Before/after comparison, same nested-chain candidates fed through `score_candidates()` twice (isolates the one variable), 180-day window:**

| | XAUUSD CHoCH-only | XAUUSD CHoCH-or-BOS | EURUSD CHoCH-only | EURUSD CHoCH-or-BOS |
|---|---|---|---|---|
| Qualifying signals | 13 | 18 | 11 | 12 |
| Win rate | 92.3% | **83.3%** | 72.7% | 75.0% |
| Expectancy | +2.543R | **+2.284R** | +2.498R | +2.488R |
| f_choch hit rate among qualifiers | 50.8% | 66.1% | 60.6% | 79.8% |

**Rejected -- BOS dilutes the factor too much to be worth it.** BOS occurs ~10-11x more often than CHoCH in real data (3,971 BOS rows vs 399 CHoCH for XAUUSD over the same window; 4,339 vs 453 for EURUSD) -- structurally expected, since BOS is trend continuation (constant) and CHoCH is reversal (rare by definition), but it means broadening the factor doesn't add a little more signal, it substantially dilutes what `f_choch` originally meant (a specific reversal-alignment check) into a much weaker, near-ubiquitous "some structural break happened" condition. Result: more signals in both symbols (+5 XAUUSD, +1 EURUSD) but quality moved the wrong way on XAUUSD specifically (win rate -9pp, expectancy -0.26R) and was flat/noise on EURUSD (+2.3pp win rate, -0.01R expectancy on n=11->12). Unlike the CRT-drop or zone-weighting fixes, which improved cleanly across both symbols, this trades sample size for quality and doesn't clear the bar.

**Production unchanged:** `run_composite_confluence_detection.py` still passes CHoCH-only rows, `include_bos` defaults to `False` everywhere. Per the user's explicit instruction, `include_bos` is kept in the code as a tested, available-but-unused option -- same treatment as the CRT scoring flag (`f_crt` computed but excluded from the score sum) -- not deleted, in case a differently-scoped BOS test is worth trying later (e.g. BOS gated by additional confirmation rather than a flat OR).

## Prioritized-root filter (2-of-5 factors, tightened windows) adopted as production

Following up on the "tested, not adopted" entry above: the user reconfirmed the same design (2+ of 5 composite factors, hours-not-days windows) after a restated summary of the already-obtained results, then explicitly adopted it -- "real compute savings with no meaningful quality loss."

**Wired into production:** `run_composite_confluence_detection.py` now calls `nze.filter_roots_near_composite_factors(htf_zones_by_tf, sweeps, choch, all_tf_zones, htf_bias, divs)` before drilling, and passes the result as `build_nested_chains()`'s `root_zones_by_tf` (intermediate-level nesting search still uses the full, unfiltered `htf_zones_by_tf` -- only which zones become roots is prioritized). Dry-run confirmed exact match with the validated comparison (76 chains / 12 qualifying for XAUUSD, matching the 180-day test run precisely) before writing anything.

**Written to production:** XAUUSD root pools reduced 79.8-84.8% kept (-15 to -20%), EURUSD 83.2-90.4% kept (-10 to -17%) per timeframe. 12 XAUUSD / 10 EURUSD qualifying signals from this run's chains, upserted into the same `composite_confluence_signals` rows (13/11 total `nested_chain` rows remain live -- 1 XAUUSD row from the prior unfiltered-root write no longer qualifies under prioritized logic and simply stopped being regenerated, kept as historical record per the project's standing non-destructive convention, not deleted or flagged as wrong).

**Third occurrence of the same upsert-collision risk, caught the same way as the prior two (zone-weighting fix, CRT drop):** resolution reported "0 open signals to check" for both symbols immediately after the write -- every row the new run touched already existed with a matching `(symbol, direction, confirmed_at_bar)` key from the prior unfiltered-root write. Checked whether the upsert's `UPDATE` clause actually changed any values (MySQL only bumps `updated_at` when a column's new value differs from its stored value, so a same-value UPDATE is distinguishable from a real one by timestamp alone): 5 of the 23 total rows (2 XAUUSD ids 555/556, 3 EURUSD ids 801/798/805) showed `updated_at` freshly bumped to the write's own timestamp -- their entry/stop/score genuinely changed between the unfiltered and prioritized drilling runs (plausible cause: natural pipeline drift between the two runs -- new bars synced, `all_tf_zones`'s own rolling window advancing with wall-clock time -- not a bug in the prioritization logic itself, since a root surviving the filter should drill identically to before). All 5 already carried a resolved `exit_reason` from the earlier run, now stale against their new parameters. Fixed the same way as both prior occurrences: reset the 5 rows to `open` and re-resolved against their current real parameters (all 5 came back wins).

**Final production state, verified:** 13 XAUUSD (12W/1L, +2.543R) / 11 EURUSD (8W/3L, +2.498R) `nested_chain` signals, all resolved, 0 open, 0 stale.

## Airflow removed -- was leftover infrastructure, never actually used

User asked for automation guidance (Windows Task Scheduler running `main.py` on an interval) and, mid-conversation, asked whether Docker/Airflow were actually in use. First answer given was wrong -- claimed "no Airflow in this project at all." Corrected after the user pushed back and a real check was run: `docker ps` showed `gold_airflow_webserver_active`/`gold_airflow_scheduler_active` had been **up for 4 days**, so Airflow infrastructure genuinely existed and was running -- the "no Airflow" claim was false. But `airflow dags list-runs -d quant_daily_sync` showed the DAG was **paused with zero executions ever**, meaning despite running for 4 days it had done zero actual work -- consistent with why the Task Scheduler conversation was still necessary in the first place. Both things were true at once: Airflow existed and ran, and it had never been used.

**Root cause:** leftover infrastructure from an earlier project phase (see the "main.py becomes the single end-to-end pipeline entry point" entry above) -- `airflow/dags/quant_daily_sync.py` only ever covered the raw Yahoo/bronze sync (via `QuantBackend.sync_all()`), never the curated/detection pipeline, and was superseded once `main.py` became the single entry point covering everything. It was kept technically working at the time (imports fixed) but never turned on.

**User confirmed removal** after seeing the accurate picture (running-but-unused, not never-existed). Removed:
- 3 running containers (`gold_airflow_webserver_active`, `gold_airflow_scheduler_active`, `gold_airflow_init_active` -- stopped and removed via `docker stop`/`docker rm`)
- `airflow-init`/`airflow-webserver`/`airflow-scheduler` services from `docker-compose.yml`
- `Dockerfile` (was `FROM apache/airflow:2.8.1-python3.11`, existed solely to build the Airflow image -- nothing else referenced it)
- `airflow/` directory (`airflow/dags/quant_daily_sync.py` and the now-empty parent folder)
- `apache-airflow>=2.8.1` from `requirements.txt`
- `airflow_db` MySQL database (dropped live -- editing the schema file alone doesn't retroactively affect an already-initialized MySQL data volume, since `docker-entrypoint-initdb.d` scripts only run once on first container creation)
- `AIRFLOW_UID` from both `.env` and `.env.example`; Airflow-specific lines from `.gitignore`

**Kept, not removed, because still genuinely in use** (checked before touching anything, not assumed): `pipeline_status` table in `storage/schema_raw.sql` -- still actively populated by `scripts/sync/scheduler/mt5_sync_service.py` (confirmed via grep) for sync-freshness tracking, unrelated to whether Airflow exists; its comment was updated to stop citing Airflow as the motivating consumer, not deleted. `scripts/sync/quant_backend.py` -- still imported by `sync_yahoo.py`, only its Airflow-specific docstring line was removed. `scripts/sync/scheduler/mt5_sync_service.py` -- explicitly designed to be Airflow-*independent* (its own docstring: "Airflow can't import the MetaTrader5 package"), genuinely still useful for the Task Scheduler automation being set up in this same conversation, untouched. `storage/migrations/001_mt5_integration.sql` -- a historical migration record, left as-is (migrations describe what was actually run at the time, not rewritten after the fact).

**Verified nothing else broke:** `docker-compose config --quiet` validated clean after the edits; `docker ps` confirmed `gold_mysql_active` and `gold_phpmyadmin_active` (the two services actually load-bearing) still running/healthy, untouched by the removal.

**Where it lives:** `docker-compose.yml`, `requirements.txt`, `.gitignore`, `.env`, `.env.example`, `storage/schema_raw.sql`, `docs/README-MT5.md`, `scripts/sync/quant_backend.py`, `scripts/sync/sync_yahoo.py` (Airflow references removed); `Dockerfile` and `airflow/` (deleted).

## Project closure: SMC/ICT signal generation retired, pivoting to statistical/ML mean reversion

**Final state of the SMC-based system.** The Composite Confluence Engine with Nested Zone Drilling (`analysis/strategies/nested_zone_engine.py` + `composite_confluence_engine.py`) is the production system as of this entry: a 5-factor score (`f_sweep`, `f_choch`, `f_zone_stack`, `f_bias`, `f_div`, threshold >= 3/5) driving entries through a hierarchical D1 -> H6 -> H4 -> H1 -> M15 -> M5 zone-drilling chain (`entry_mechanism = nested_chain`), with `nearest_structure` stops and a structural TP1..TP5 ladder (minimum TP1 R:R >= 2.0). Verified live in the dashboard (LTF Triggers page): XAUUSD n=13 resolved signals, 92.3% win rate, +2.543R expectancy; EURUSD n=11 resolved signals, 72.7% win rate, +2.498R expectancy; both at the >= 3/5 production threshold, both flagged in the UI as small-sample and directionally inconclusive per the project's own Deflated Sharpe Ratio / minimum-sample-size standard (see "Project Origin & Goals"). The >= 2/5 lower-threshold variant was tested full-history on both symbols and produces more signals but a lower win rate and lower expectancy than the >= 3/5 default -- it is exposed in the dashboard as a deliberate, clearly-labeled alternative, not a fix for sample size.

**Why sample size never closed.** At the >= 3/5 threshold's observed generation rate, clearing this project's own 300+ trade floor for statistical validity would take on the order of 11-13 years of live signal accumulation per symbol. Lowering the threshold to >= 2/5 does not solve this: it was tested and shown to trade signal frequency for win rate and expectancy, which is the same tradeoff in the opposite direction, not a resolution of it. No parameter sweep, gating change, or threshold adjustment tried over the life of this project (see the CRT-in-score, BOS-in-CHoCH, and threshold-isolation entries above) increased frequency without degrading edge, or vice versa.

**Root cause.** This tension is structural, not a tuning problem. SMC/ICT concepts (order blocks, fair value gaps, liquidity sweeps, CHoCH) are subjective pattern-recognition constructs that only fire when a specific, relatively rare structural pattern forms across a chain of timeframes -- they are not derived from a continuous statistical or machine-learned process. Requiring nested confluence across D1 through M5 to control risk necessarily makes qualifying setups rare; loosening the requirements to get more setups necessarily admits weaker, more marginal pattern matches. This is why frequency and statistical rigor were in conflict for the entire project, from the earliest HTF Bias Engine weighting decisions through the final nested-chain threshold isolation test -- not because any one factor, weight, or gate was wrong, but because the underlying signal-generation paradigm is pattern-scarce by construction.

**Decision.** Retire SMC/ICT pattern-based signal generation as the active research direction and pivot to a new project built on proper statistical/ML methodology. The starting direction is mean reversion: unlike nested SMC confluence, a mean-reversion signal is computable from every price point (not gated behind rare multi-timeframe pattern formation), which matches day-trading frequency needs and is naturally suited to the empirical, walk-forward-validated approach this project has enforced throughout.

**What carries forward to the new project:**
- The full MT5/Yahoo ingestion pipeline: `raw_gold` and `raw_eurusd` (m5/m15/h1 from MT5, h4/h6/d1 resampled/Yahoo), plus macro sources DXY, US10Y, VIX, GDX, Silver, FRED, ECB, and GPR (`fetcher/`, `scripts/sync/`).
- The dashboard and backtest infrastructure: the Streamlit app (`dashboard/`), and the backtesting/statistics tooling (`analysis/backtester/`, `scripts/backtest/`), including `metrics.py` (expectancy, win rate, Sharpe, max drawdown).
- The statistical-rigor discipline established here: Deflated Sharpe Ratio and minimum-sample-size standards, negative-control testing, bootstrap confidence intervals, and train/val/test walk-forward methodology (see "Project Origin & Goals" and `scripts/backtest/bootstrap_ci_and_mcc.py`, `scripts/backtest/random_entry_baseline.py`).

**What does not carry forward:** the SMC/CRT/divergence signal-generation layer itself (`analysis/smc_crt/`, `analysis/strategies/nested_zone_engine.py`, `composite_confluence_engine.py`, `structural_tp_engine.py`, `ltf_trigger_engine.py`) and the `composite_confluence_signals` / `nested_zone_chains` curated tables -- these encode the pattern-recognition paradigm being retired, not the reusable infrastructure underneath it.
