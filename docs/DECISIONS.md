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

**Why:** the two have entirely different blockers, not a shared one. EUR vs yield-spread is deferred indefinitely because no EU/German government yield data source currently exists anywhere in the pipeline — every other inter-market model (XAU vs DXY/US10Y/GDX/SPDR, COT gold/EUR) had a real, already-integrated data source to build against; this one doesn't. MTF Alignment Divergence is a structurally different kind of divergence than the other 11 — it would compare the *same* instrument's reading across *different timeframes* rather than comparing two different instruments/drivers at the same timeframe, which doesn't fit the pivot-pair-vs-driver-value mechanism `TechnicalDivergenceEngine`/`IntermarketDivergenceEngine` are both built around. It would need its own comparison mechanism, not a new driver plugged into the existing one.

**Evidence:** documented directly in the module docstrings for both engines — `analysis/divergence/intermarket_divergence_state.py` for the EUR yield-spread blocker, `analysis/divergence/technical_divergence_state.py`'s "Explicitly deferred" section for MTF Alignment.

**Where it lives in code:** nowhere yet — these are the two models with no corresponding detection code, by design. `analysis/divergence/intermarket_divergence_state.py` and `technical_divergence_state.py` both note them as deferred rather than silently omitting any mention.

**Status:** deferred, not scheduled — both have a clear path forward when/if their blocker is resolved (a EU/German yield source appears; MTF alignment's own comparison mechanism gets designed), but neither is in progress.

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
