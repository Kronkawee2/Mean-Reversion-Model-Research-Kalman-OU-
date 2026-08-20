-- ============================================================
-- Step 2 (Processed) — Curated schema.
-- Phase 2a slice: SMC zone-state (smc_signals).
-- Phase 2b slice: CRT (crt_signals) — Asian range/sweep (h1) + Range
-- Equilibrium (h4/h6/d1). Added alongside smc_signals, not by editing it.
-- Phase 2c slice: indicator features (features) — EMA 20/50/200, ATR 14,
-- RSI 14 across h1/h4/h6/d1. Added alongside smc_signals/crt_signals, not
-- by editing them.
-- Phase 2d slice: Volume Profile (volume_profile) — one profile per UTC
-- session day from h1 bars (POC/VAH/VAL/HVN/LVN per bin). Added alongside
-- smc_signals/crt_signals/features, not by editing them.
-- Phase 2e slice: Technical Divergence (divergence_signals) — RSI Regular
-- + Hidden Bullish/Bearish. See
-- analysis/divergence/technical_divergence_state.py for what's still
-- deferred (Stochastic/CCI, inter-market, MTF alignment).
-- Phase 2f slice: OBV added to `features` (alongside ema/atr/rsi, not a
-- separate table for one indicator) and OBV Regular + Hidden divergence
-- added to divergence_signals (divergence_type='obv').
-- Phase 2g slice: Stochastic %K/%D (14,3,3) and CCI 20 added to
-- `features`; Stochastic + CCI Regular/Hidden divergence added to
-- divergence_signals (divergence_type='stochastic'/'cci'), completing
-- Category 2 (Technical) of the divergence matrix.
-- Phase 2h slice: Inter-market divergence (divergence_type=
-- 'xau_dxy'/'eur_dxy'/'xau_us10y'/'xau_gdx', Regular+Hidden, d1 only)
-- added to divergence_signals — built fresh on the Category 2 framework
-- rather than reusing detection.py's detect_intermarket_divergence /
-- detect_cot_divergence (see analysis/divergence/
-- intermarket_divergence_state.py for why: those aren't pivot-based
-- despite their docstrings, and fire on 32% of bars on real data). EUR
-- vs yield-spread and both COT models remain deferred — no EU/German
-- yield source, and COT needs a new fetcher plus a granularity fix.
-- No table changes needed — divergence_signals' existing schema
-- (divergence_type VARCHAR(20), divergence_class, direction, pivot
-- columns) already accommodated this without modification.
-- Phase 2i slice: divergence_type='cot_gold'/'cot_eur'/'xau_spdr' added to
-- divergence_signals (new raw sources: raw_cot, raw_spdr — see
-- fetcher/cot_fetcher.py, fetcher/spdr_fetcher.py). No table changes
-- needed here either.
-- Phase 3a slice: HTF Bias Engine (htf_bias) — Pass 1 of strategies/.
-- Aggregates SMC zone-state (dominant weight), CRT equilibrium, indicator
-- trend, volume profile, and h1 technical divergence into one bullish/
-- bearish/neutral bias + confluence score per h1 bar. See
-- analysis/strategies/htf_bias_engine.py for the weighting design and
-- why h1 (not h4) is the primary timeframe. LTF trigger logic, entry/
-- stop/target, and risk management are explicitly out of scope this pass.
-- ============================================================

CREATE DATABASE IF NOT EXISTS curated_gold
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE curated_gold;

GRANT ALL PRIVILEGES ON curated_gold.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS smc_signals (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,

    -- order_block_bullish / order_block_bearish / fvg_bullish / fvg_bearish /
    -- swing_resistance / swing_support
    zone_type          ENUM('order_block_bullish','order_block_bearish',
                             'fvg_bullish','fvg_bearish',
                             'swing_resistance','swing_support') NOT NULL,

    zone_top           DECIMAL(16,5) NOT NULL,
    zone_bottom        DECIMAL(16,5) NOT NULL,

    state              ENUM('active','mitigated','invalidated') NOT NULL DEFAULT 'active',
    created_at_bar     DATETIME NOT NULL,
    mitigated_at_bar   DATETIME NULL,
    invalidated_at_bar DATETIME NULL,

    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running detection over the same history must upsert, not duplicate:
    -- one zone per (symbol, timeframe, zone_type, created_at_bar). Two
    -- distinct zones of the same type can't be created on the same bar.
    UNIQUE KEY uq_zone (symbol, timeframe, zone_type, created_at_bar),
    INDEX idx_state (symbol, timeframe, state),
    INDEX idx_created (created_at_bar DESC)
) ENGINE=InnoDB;

-- CRT signals: Asian range levels + London/NY sweeps (timeframe='h1', two
-- rows per session day: asian_range_high / asian_range_low) and Range
-- Equilibrium (timeframe='h4'/'h6'/'d1', one row per candle). See
-- analysis/smc_crt/crt_state.py module docstring for why these two signal
-- families use a 2-state pending/swept/expired model and a stateless
-- per-candle snapshot respectively, instead of smc_signals' 3-state
-- active/mitigated/invalidated lifecycle.
CREATE TABLE IF NOT EXISTS crt_signals (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,

    signal_type        ENUM('asian_range_high','asian_range_low','equilibrium') NOT NULL,

    -- asian_range_high/low only: the Asian session's UTC calendar date.
    session_date       DATE NULL,
    -- asian_range_high/low: 00:00 UTC anchor of session_date.
    -- equilibrium: the candle's own price_datetime.
    bar_datetime       DATETIME NOT NULL,

    -- asian_range_high/low only: the asian high (for _high rows) or asian
    -- low (for _low rows) price level.
    level_price        DECIMAL(16,5) NULL,

    -- equilibrium only: the h4/h6/d1 candle's own high/low and 50% level.
    range_high         DECIMAL(16,5) NULL,
    range_low          DECIMAL(16,5) NULL,
    equilibrium_price  DECIMAL(16,5) NULL,
    -- equilibrium only: classification of that candle's own close vs
    -- equilibrium_price. Not a state — recomputed fresh per candle.
    zone_bias          ENUM('premium','discount') NULL,

    -- asian_range_high/low only: pending (untested) -> swept (a London/NY
    -- h1 candle wicked through and closed back inside) or expired (no
    -- sweep before the next Asian session began). NULL for equilibrium rows.
    state              ENUM('pending','swept','expired') NULL,
    -- asian_range_high/low only, set when state='swept': 'bearish' for a
    -- swept high, 'bullish' for a swept low.
    sweep_direction    ENUM('bullish','bearish') NULL,
    swept_at_bar       DATETIME NULL,
    expired_at_bar     DATETIME NULL,

    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running detection over the same history must upsert, not
    -- duplicate: one row per (symbol, timeframe, signal_type, bar_datetime).
    UNIQUE KEY uq_crt_signal (symbol, timeframe, signal_type, bar_datetime),
    INDEX idx_state (symbol, timeframe, state),
    INDEX idx_bar (bar_datetime DESC)
) ENGINE=InnoDB;

-- Liquidity sweeps (BSL/SSL): one row per detected point-in-time sweep
-- event against a swing high/low (retail stop-cluster level). Unlike
-- crt_signals' asian_range_high/low, there is no pending/expired lifecycle
-- here: a sweep is confirmed the instant the wick-through-and-close-back-in
-- bar closes, and the reference swing level has no expiration (it stays a
-- live target until a newer swing pivot replaces it). Shape matches
-- divergence_signals' point-in-time-event pattern, not either zone table's
-- lifecycle pattern.
CREATE TABLE IF NOT EXISTS liquidity_sweeps (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    sweep_type         ENUM('bsl','ssl') NOT NULL,
    -- bsl (swing-high wick swept) -> bearish; ssl (swing-low wick swept) -> bullish.
    direction          ENUM('bullish','bearish') NOT NULL,
    swept_level_price  DECIMAL(16,5) NOT NULL,
    bar_datetime       DATETIME NOT NULL,
    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sweep (symbol, timeframe, sweep_type, bar_datetime),
    INDEX idx_bar (symbol, timeframe, bar_datetime DESC)
) ENGINE=InnoDB;

-- Indicator features: one row per bar per timeframe, all indicator columns
-- together (not a separate table per indicator) so a single query gets the
-- full indicator snapshot for a bar. h6 rows are computed by resampling h1
-- (see analysis/features/indicator_features.py) since the raw `h6` table
-- in schema_raw.sql was never actually populated by any sync job.
CREATE TABLE IF NOT EXISTS features (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    bar_datetime       DATETIME NOT NULL,

    ema_20             DECIMAL(16,5) NULL,
    ema_50             DECIMAL(16,5) NULL,
    ema_200            DECIMAL(16,5) NULL,
    atr_14             DECIMAL(16,6) NULL,
    rsi_14             DECIMAL(8,3)  NULL,
    -- Cumulative On-Balance Volume (Granville 1963) — signed, can be
    -- negative, and grows unboundedly over a long history, hence the wide
    -- DECIMAL rather than matching the narrower indicator columns above.
    obv                DECIMAL(24,4) NULL,
    -- Stochastic Oscillator (14,3,3 Slow Stochastic convention) and CCI 20.
    stoch_k            DECIMAL(8,3)  NULL,
    stoch_d            DECIMAL(8,3)  NULL,
    cci_20             DECIMAL(10,3) NULL,

    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running the feature pipeline over the same history must upsert,
    -- not duplicate: one row per (symbol, timeframe, bar_datetime).
    UNIQUE KEY uq_feature_bar (symbol, timeframe, bar_datetime),
    INDEX idx_bar (bar_datetime DESC)
) ENGINE=InnoDB;

-- Volume Profile: one row per price bin per UTC session day (timeframe is
-- always the source bar timeframe, 'h1' — see
-- analysis/volume_profile/session_profile.py module docstring for why h1
-- and per-session-day were chosen over other timeframes/windows).
-- session_poc/session_vah/session_val/session_total_volume/num_bins are
-- repeated on every bin row of that session so a query against this table
-- alone (no join) gets both the full histogram and the session summary.
CREATE TABLE IF NOT EXISTS volume_profile (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                VARCHAR(20)   NOT NULL,
    timeframe             VARCHAR(10)   NOT NULL,
    session_date          DATE NOT NULL,
    bin_index             SMALLINT NOT NULL,

    bin_low               DECIMAL(16,5) NOT NULL,
    bin_high              DECIMAL(16,5) NOT NULL,
    bin_center            DECIMAL(16,5) NOT NULL,
    bin_volume            DECIMAL(20,4) NOT NULL,

    -- is_poc: this bin is the session's Point of Control (max-volume bin).
    -- in_value_area: this bin falls within the 70% Value Area expansion
    -- from POC (Steidlmayer Market Profile method).
    -- is_hvn / is_lvn: this bin is a local volume maximum/minimum relative
    -- to its immediate neighbor bins (not a global mean/std threshold —
    -- see calculator.py's compute_profile for why).
    is_poc                BOOLEAN NOT NULL DEFAULT FALSE,
    in_value_area         BOOLEAN NOT NULL DEFAULT FALSE,
    is_hvn                BOOLEAN NOT NULL DEFAULT FALSE,
    is_lvn                BOOLEAN NOT NULL DEFAULT FALSE,

    session_poc           DECIMAL(16,5) NOT NULL,
    session_vah           DECIMAL(16,5) NOT NULL,
    session_val           DECIMAL(16,5) NOT NULL,
    session_total_volume  DECIMAL(20,4) NOT NULL,
    num_bins              SMALLINT NOT NULL,

    inserted_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running over the same history must upsert, not duplicate: one row
    -- per (symbol, timeframe, session_date, bin_index).
    UNIQUE KEY uq_vp_bin (symbol, timeframe, session_date, bin_index),
    INDEX idx_session (symbol, timeframe, session_date),
    INDEX idx_poc (symbol, timeframe, is_poc)
) ENGINE=InnoDB;

-- Technical Divergence: one row per confirmed divergence signal (not per
-- bar). divergence_type is the indicator used ('rsi' this pass; 'obv',
-- 'stochastic', 'cci' once those indicators exist in analysis/features/).
-- divergence_class distinguishes Regular (reversal) from Hidden
-- (continuation) — these are a separate dimension from direction
-- (bullish/bearish), not a relabeling of it: a REGULAR_BULLISH and a
-- HIDDEN_BULLISH both have direction='bullish' but mean opposite things
-- (reversal vs continuation), so direction alone can't carry this.
CREATE TABLE IF NOT EXISTS divergence_signals (
    id                     BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                 VARCHAR(20)   NOT NULL,
    timeframe              VARCHAR(10)   NOT NULL,
    -- Bar at which the divergence is confirmed (curr pivot + pivot_window
    -- bars, once enough future bars exist to confirm curr was a pivot).
    bar_datetime           DATETIME NOT NULL,

    divergence_type        VARCHAR(20)   NOT NULL,
    divergence_class       ENUM('regular','hidden') NOT NULL,
    direction              ENUM('bullish','bearish') NOT NULL,

    prev_pivot_datetime    DATETIME NOT NULL,
    prev_pivot_price       DECIMAL(16,5) NOT NULL,
    prev_pivot_indicator   DECIMAL(24,4) NOT NULL,

    curr_pivot_datetime    DATETIME NOT NULL,
    curr_pivot_price       DECIMAL(16,5) NOT NULL,
    curr_pivot_indicator   DECIMAL(24,4) NOT NULL,

    inserted_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running over the same history must upsert, not duplicate: one
    -- signal per (symbol, timeframe, divergence_type, divergence_class,
    -- curr pivot bar) — divergence_class is part of the key because the
    -- same curr_pivot_datetime could in principle appear in both a
    -- regular and a hidden classification (different pivot pairs sharing
    -- an endpoint), and they are different signals, not duplicates.
    UNIQUE KEY uq_divergence (symbol, timeframe, divergence_type, divergence_class, curr_pivot_datetime),
    INDEX idx_bar (symbol, timeframe, bar_datetime DESC),
    INDEX idx_direction (symbol, timeframe, divergence_type, divergence_class, direction)
) ENGINE=InnoDB;

-- HTF Bias: one row per h1 bar (h1 is the primary/authoritative HTF
-- timeframe this pass — see analysis/strategies/htf_bias_engine.py for
-- why). Every component's raw contribution is stored alongside the final
-- bias/confluence_score so a query against this table alone shows which
-- signal types drove a given bias, not just the end result.
CREATE TABLE IF NOT EXISTS htf_bias (
    id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                   VARCHAR(20)   NOT NULL,
    timeframe                VARCHAR(10)   NOT NULL,
    bar_datetime             DATETIME NOT NULL,

    bias                     ENUM('bullish','bearish','neutral') NOT NULL,
    confluence_score         DECIMAL(6,2) NOT NULL,   -- final, clipped to [-100,100]
    raw_score_before_caution DECIMAL(6,2) NOT NULL,   -- pre-regular-divergence-caution total

    smc_contribution         DECIMAL(6,2) NOT NULL,
    smc_active_bullish_zones SMALLINT NOT NULL,
    smc_active_bearish_zones SMALLINT NOT NULL,

    crt_contribution         DECIMAL(6,2) NOT NULL,
    crt_equilibrium_bias     ENUM('premium','discount') NULL,

    indicator_contribution      DECIMAL(6,2) NOT NULL,
    volume_profile_contribution DECIMAL(6,2) NOT NULL,

    -- Hidden (continuation) divergence reinforces the score, additively,
    -- in its own signaled direction. Regular (reversal-risk) divergence
    -- instead multiplicatively dampens the WHOLE score toward neutral
    -- (regular_divergence_caution_factor = 0.85^regular_divergence_count)
    -- rather than casting its own directional vote — see the module
    -- docstring for why this matches "regular = caution" rather than
    -- "regular = a competing direction."
    hidden_divergence_contribution DECIMAL(6,2) NOT NULL,
    hidden_divergence_count        SMALLINT NOT NULL,
    regular_divergence_caution_factor DECIMAL(5,4) NOT NULL,
    regular_divergence_count          SMALLINT NOT NULL,

    -- Liquidity sweep (BSL/SSL): single most-recent-event read within the
    -- same lookback window as divergence, not a sum over the window (see
    -- htf_bias_engine.py module docstring for why summing was deliberately
    -- avoided here). NULL direction means no sweep in the lookback window.
    liquidity_sweep_contribution DECIMAL(6,2) NOT NULL,
    liquidity_sweep_direction    ENUM('bullish','bearish') NULL,

    -- Session weighting: classification of the bar's own UTC session, and
    -- the bounded multiplier actually applied to crt_contribution and
    -- liquidity_sweep_contribution only (SMC/indicator/volume-profile are
    -- not session-scaled). Stored for transparency/debugging, not itself
    -- a separate additive component.
    session              ENUM('asian','london','ny','killzone') NOT NULL,
    session_multiplier   DECIMAL(4,3) NOT NULL,

    inserted_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running over the same history must upsert, not duplicate: one
    -- bias row per (symbol, timeframe, bar_datetime).
    UNIQUE KEY uq_bias_bar (symbol, timeframe, bar_datetime),
    INDEX idx_bias (symbol, timeframe, bias),
    INDEX idx_bar (bar_datetime DESC)
) ENGINE=InnoDB;

-- LTF trigger signals (Pass 2 of strategies/): confirms an entry when
-- price enters an active HTF (h1) SMC zone and LTF structure (m5/m15)
-- confirms a reversal in the zone's expected direction. Two selectable
-- confirmation modes persist to the SAME table (mode is a column, not two
-- tables) so both can coexist and be compared on real data -- see
-- analysis/strategies/ltf_trigger_engine.py for the full design reasoning.
-- 'choch_only': zone touch + matching-direction CHoCH. 'choch_sweep':
-- choch_only's requirements PLUS a same-direction liquidity sweep that
-- precedes the CHoCH, both within the same confirmation window. The
-- htf_zone_* columns are a composite reference back to the specific
-- smc_signals row (matching this project's established pattern of
-- composite natural-key cross-references rather than surrogate FKs, e.g.
-- CRT's signal_type+bar_datetime), not a numeric foreign key.
CREATE TABLE IF NOT EXISTS ltf_trigger_signals (
    id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                   VARCHAR(20)   NOT NULL,
    ltf_timeframe            VARCHAR(10)   NOT NULL,
    mode                     ENUM('choch_only','choch_sweep') NOT NULL,
    direction                ENUM('bullish','bearish') NOT NULL,

    -- 'confluence_bullish_mode_a'/'_mode_b' and 'confluence_bearish_mode_a'/
    -- '_mode_b' cover triggers sourced from confluence_zones (multi-factor,
    -- no single zone_type of its own) -- see zone_source/confluence_zone_id
    -- below for how those are told apart from single-factor smc_signals
    -- triggers. The confluence_mode is baked into this value (not left to
    -- direction alone) because a mode_b_3factor zone is BY DEFINITION also
    -- a mode_a_2factor zone of the same underlying cluster (same
    -- last_factor_at_bar) -- a direction-only value made uq_trigger below
    -- unable to tell the two modes' triggers apart, and MySQL's ON
    -- DUPLICATE KEY UPDATE silently merged one mode's rows into the
    -- other's (see docs/DECISIONS.md).
    htf_zone_type            ENUM('order_block_bullish','order_block_bearish',
                                   'fvg_bullish','fvg_bearish',
                                   'swing_resistance','swing_support',
                                   'confluence_bullish_mode_a','confluence_bullish_mode_b',
                                   'confluence_bearish_mode_a','confluence_bearish_mode_b') NOT NULL,
    htf_zone_top             DECIMAL(16,5) NOT NULL,
    htf_zone_bottom          DECIMAL(16,5) NOT NULL,
    htf_zone_created_at_bar  DATETIME NOT NULL,

    -- Confluence Zone Engine LTF entry-finding pass (see
    -- analysis/strategies/confluence_ltf_trigger.py): zone_source
    -- distinguishes this row's HTF zone origin. confluence_zone_id is a
    -- soft FK into confluence_zones.id (NULL for smc_signals-sourced
    -- rows). confluence_mode mirrors confluence_zones.mode (NULL unless
    -- zone_source='confluence_zone'). zone_range_used records whether
    -- htf_zone_top/htf_zone_bottom above hold the confluence zone's
    -- CORE range (entry confirmed inside the multi-factor overlap --
    -- tighter stop) or its FULL range (confirmed only inside the union,
    -- same behavior as a single-factor zone) -- see module docstring for
    -- the full core-first-fallback-to-full selection rule.
    zone_source              ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    confluence_zone_id       BIGINT NULL,
    confluence_mode          ENUM('mode_a_2factor','mode_b_3factor') NULL,
    zone_range_used          ENUM('full','core') NULL,

    -- Confluence-aware target selection (see docs/DECISIONS.md, target-
    -- selection fix pass): whether the opposing-zone search below read
    -- smc_signals single-factor zones (original behavior, default) or
    -- confluence_zones of the SAME mode as this trigger's own entry zone.
    -- A second, orthogonal dimension from zone_source above -- a
    -- confluence-sourced ENTRY can be tested with either target source,
    -- which is exactly the controlled A/B this pass needed (same entry,
    -- only the target side varies). Included in both unique keys below so
    -- the two target variants persist as separate rows, not overwrite
    -- each other.
    target_zone_source       ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',

    touch_bar_datetime       DATETIME NOT NULL,
    choch_bar_datetime       DATETIME NOT NULL,
    -- choch_sweep only; NULL for choch_only.
    sweep_bar_datetime       DATETIME NULL,
    sweep_type               ENUM('bsl','ssl') NULL,

    -- max(touch, choch, sweep) -- the bar at which every required
    -- condition first became simultaneously true, i.e. the actual
    -- actionable moment a live system would have produced this signal at.
    confirmed_at_bar         DATETIME NOT NULL,

    -- Structural TP (Option 2, confirmed with the user over Options 1/3 --
    -- fewest tunable parameters given <2yr of one-directional history): TP
    -- is not a chosen ratio, it's read off the nearest active OPPOSING zone
    -- ahead of price -- see analysis/strategies/structural_tp_engine.py.
    -- entry_price = LTF close at confirmed_at_bar. stop_price = the far
    -- edge of the trigger's OWN htf_zone (htf_zone_bottom for bullish,
    -- htf_zone_top for bearish) -- the natural invalidation point. The
    -- opposing zone lookup is causal: only zones with created_at_bar <=
    -- confirmed_at_bar and not yet invalidated as of confirmed_at_bar are
    -- eligible, same active-window pattern as htf_bias/zone queries
    -- elsewhere. target_price sits STRUCTURAL_TP_FRACTION (0.85, flagged
    -- unvalidated same as CONFIRMATION_WINDOW_BARS) of the way from entry
    -- to the opposing zone's near edge, not the full distance. structural_rr
    -- is computed directly from entry/stop/target, never chosen.
    -- target_status='no_opposing_zone' when no eligible opposing zone
    -- exists (fallback = skip, not a default R:R -- see engine module
    -- docstring for why) -- target/rr columns stay NULL in that case, and
    -- the row is excluded from any backtest requiring a TP.
    -- target_status='invalid_geometry' covers the (should be rare)
    -- edge case where entry_price has already breached the stop.
    entry_price              DECIMAL(16,5) NULL,
    stop_price                DECIMAL(16,5) NULL,
    -- 'confluence_bullish'/'confluence_bearish' cover a confluence-zone
    -- opposing wall (target_zone_source='confluence_zone') -- unlike
    -- htf_zone_type, mode doesn't need to be baked in here since
    -- opposing_zone_type isn't part of any unique key.
    opposing_zone_type       ENUM('order_block_bullish','order_block_bearish',
                                   'fvg_bullish','fvg_bearish',
                                   'swing_resistance','swing_support',
                                   'confluence_bullish','confluence_bearish') NULL,
    opposing_zone_top        DECIMAL(16,5) NULL,
    opposing_zone_bottom     DECIMAL(16,5) NULL,
    target_price             DECIMAL(16,5) NULL,
    structural_rr            DECIMAL(8,3) NULL,
    target_status            ENUM('structural','no_opposing_zone','invalid_geometry','stop_too_tight') NULL,

    inserted_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running detection over the same history must upsert, not
    -- duplicate: one row per distinct (zone, touch, choch, target source)
    -- confirmation.
    UNIQUE KEY uq_trigger (symbol, ltf_timeframe, mode, htf_zone_type,
                            htf_zone_created_at_bar, touch_bar_datetime, choch_bar_datetime,
                            target_zone_source),
    -- Extra safety net for confluence-sourced rows, on top of htf_zone_type
    -- now encoding confluence_mode (see that column's comment): two
    -- DIFFERENT confluence zones of the same direction/mode that happen to
    -- share both a created_at_bar (last_factor_at_bar) and a touch/CHoCH
    -- bar (real, observed in practice when zones overlap in price) would
    -- still incorrectly collide under uq_trigger alone. confluence_zone_id
    -- disambiguates them directly; it's NULL for smc_signals-sourced rows,
    -- which MySQL's NULL-is-never-equal unique-index semantics correctly
    -- exempt from this key (they're already covered by uq_trigger above).
    UNIQUE KEY uq_trigger_confluence (symbol, ltf_timeframe, mode, confluence_zone_id,
                                       touch_bar_datetime, choch_bar_datetime, target_zone_source),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode),
    INDEX idx_confirmed (confirmed_at_bar DESC)
) ENGINE=InnoDB;

-- Structural Backtest (Pass 3 of strategies/): turns confirmed LTF trigger
-- signals with a valid structural TP into an actual simulated trade
-- sequence. See analysis/backtester/structural_backtest_engine.py and
-- analysis/backtester/deflated_sharpe.py module docstrings for the full
-- design: one-trade-at-a-time per (symbol, ltf_timeframe, mode) matching
-- the fixed-0.01-lot single-account context, ambiguous same-bar SL/TP
-- resolved via m5 drilldown (conservative SL-first fallback when even that
-- is ambiguous or unavailable), no artificial max holding period, and a
-- Deflated Sharpe Ratio (Bailey & Lopez de Prado) computed against the
-- Mode A vs Mode B comparison as the trial set -- see that module's
-- docstring for the explicit limitations of that N=2 estimate.
-- backtest_trades: one row per trade ACTUALLY TAKEN (signals skipped for
-- overlap never appear here -- see backtest_runs.n_trades_skipped_overlap
-- for that count). running_equity_r lets the equity curve be reconstructed
-- by ORDER BY entry_bar_datetime without re-deriving it from r_outcome.
CREATE TABLE IF NOT EXISTS backtest_trades (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    -- Soft FK into ltf_trigger_signals.id -- the exact trigger this
    -- trade came from. Required as the disambiguator in uq_backtest_trade
    -- below now that concurrent trades are allowed: two different HTF
    -- zones can genuinely share the same entry_bar_datetime, so that
    -- column alone is no longer a unique identifier for a trade. Added
    -- after older confluence-zone backtest rows already existed (see
    -- docs/DECISIONS.md) -- those specific pre-existing rows were
    -- backfilled with their own backtest_trades.id (NOT a genuine link
    -- to ltf_trigger_signals for that older slice) purely to satisfy
    -- this key; every row inserted from this schema version onward
    -- carries the real source trigger id.
    source_trigger_id     BIGINT NOT NULL,
    symbol                VARCHAR(20)   NOT NULL,
    ltf_timeframe         VARCHAR(10)   NOT NULL,
    mode                  ENUM('choch_only','choch_sweep') NOT NULL,
    -- Confluence LTF Trigger backtest (see docs/DECISIONS.md): zone_source
    -- distinguishes which ltf_trigger_signals pool this trade's entry came
    -- from. confluence_mode uses an explicit 'none' sentinel rather than
    -- NULL for smc_signals-sourced rows -- NULL would break
    -- uq_backtest_trade's uniqueness guarantee for those rows (MySQL never
    -- treats two NULLs as equal in a unique index), and mode_a_2factor vs
    -- mode_b_3factor runs for the SAME underlying cluster can genuinely
    -- share an entry_bar_datetime (a mode_b zone is always also a mode_a
    -- zone of the same cluster), so this dimension must be a real,
    -- comparable value in the key, not nullable.
    zone_source           ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    confluence_mode        ENUM('none','mode_a_2factor','mode_b_3factor') NOT NULL DEFAULT 'none',
    -- Mirrors ltf_trigger_signals.target_zone_source -- which opposing-zone
    -- pool produced this trade's target_price. Orthogonal to zone_source
    -- above (a confluence-sourced entry can pair with either target
    -- source), included in uq_backtest_trade below for the same reason.
    target_zone_source     ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    direction             ENUM('bullish','bearish') NOT NULL,

    entry_bar_datetime    DATETIME NOT NULL,
    entry_price           DECIMAL(16,5) NOT NULL,
    stop_price            DECIMAL(16,5) NOT NULL,
    target_price          DECIMAL(16,5) NOT NULL,
    structural_rr         DECIMAL(8,3) NOT NULL,

    htf_zone_type         ENUM('order_block_bullish','order_block_bearish',
                                'fvg_bullish','fvg_bearish',
                                'swing_resistance','swing_support',
                                'confluence_bullish_mode_a','confluence_bullish_mode_b',
                                'confluence_bearish_mode_a','confluence_bearish_mode_b') NOT NULL,
    htf_zone_top          DECIMAL(16,5) NOT NULL,
    htf_zone_bottom       DECIMAL(16,5) NOT NULL,

    -- NULL exit_bar_datetime/bars_held/r_outcome only for exit_reason='open_at_data_end'.
    exit_bar_datetime     DATETIME NULL,
    exit_reason           ENUM('win','loss','open_at_data_end') NOT NULL,
    bars_held             INT NULL,
    resolution_method     ENUM('m15_clean','m5_drilldown','m5_still_ambiguous_sl_assumed',
                                'm5_data_missing_sl_assumed','m5_no_subbar_breach_sl_assumed',
                                'open_at_data_end') NOT NULL,
    r_outcome             DECIMAL(8,3) NULL,
    running_equity_r      DECIMAL(10,3) NULL,

    inserted_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- A full re-simulation deletes and re-inserts all rows for a
    -- (symbol, ltf_timeframe, mode, zone_source, confluence_mode) rather
    -- than upserting -- the trade count itself can change between runs if
    -- upstream logic changes, and an upsert-only script would leave stale
    -- orphaned rows (the exact class of bug this project has been bitten
    -- by before).
    UNIQUE KEY uq_backtest_trade (symbol, ltf_timeframe, mode, zone_source, confluence_mode,
                                   target_zone_source, source_trigger_id),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode),
    INDEX idx_entry (entry_bar_datetime DESC)
) ENGINE=InnoDB;

-- backtest_runs: one row per (symbol, ltf_timeframe, mode, period), period
-- in {'full','test'} -- 'test' is the held-out ~30% (by calendar time, not
-- trade count) of history never looked at until final evaluation; 'full'
-- covers everything. Both are computed from the SAME single chronological
-- trade simulation (see script), sliced by entry_bar_datetime >=
-- oos_cutoff_date for 'test' -- not a separate re-simulation restarting
-- position state at the cutoff, since a real account could carry an
-- in-sample-opened position across that boundary.
CREATE TABLE IF NOT EXISTS backtest_runs (
    id                          BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                      VARCHAR(20) NOT NULL,
    ltf_timeframe               VARCHAR(10) NOT NULL,
    mode                        ENUM('choch_only','choch_sweep') NOT NULL,
    -- Same zone_source/confluence_mode dimension and 'none'-sentinel
    -- reasoning as backtest_trades above.
    zone_source                 ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    confluence_mode              ENUM('none','mode_a_2factor','mode_b_3factor') NOT NULL DEFAULT 'none',
    target_zone_source           ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    period                      ENUM('full','test') NOT NULL,

    period_start                DATETIME NOT NULL,
    period_end                  DATETIME NOT NULL,
    oos_cutoff_date             DATETIME NOT NULL,

    n_signals_structural        INT NOT NULL,
    n_trades_taken               INT NOT NULL,
    n_trades_skipped_overlap    INT NOT NULL,
    n_wins                      INT NOT NULL,
    n_losses                    INT NOT NULL,
    n_open_at_data_end          INT NOT NULL,

    win_rate                    DECIMAL(6,4) NULL,
    profit_factor               DECIMAL(10,4) NULL,
    expectancy_r                DECIMAL(8,4) NULL,
    max_drawdown_r              DECIMAL(10,4) NULL,

    -- Sharpe here is a per-TRADE (not time-annualized) ratio -- see
    -- deflated_sharpe.py module docstring for why. n_trials_for_dsr and
    -- sr_variance_across_trials are the DSR's selection-bias inputs
    -- (N=2: this mode's Sharpe vs the OTHER mode's Sharpe for the same
    -- symbol/period, an explicitly-flagged rough estimate -- see that
    -- module's docstring for the full limitation).
    sharpe_ratio                DECIMAL(8,4) NULL,
    skewness                    DECIMAL(8,4) NULL,
    kurtosis                    DECIMAL(8,4) NULL,
    n_trials_for_dsr            SMALLINT NULL,
    sr_variance_across_trials   DECIMAL(10,6) NULL,
    sr0_threshold               DECIMAL(8,4) NULL,
    deflated_sharpe_ratio       DECIMAL(8,6) NULL,
    psr_vs_zero                 DECIMAL(8,6) NULL,

    -- ~200 trades/12 months floor discussed early in this project, scaled
    -- to this row's own period_start/period_end duration.
    min_sample_floor_required   INT NULL,
    meets_min_sample_floor      BOOLEAN NULL,

    -- Outcome-resolution diagnostics (see structural_backtest_engine.py):
    -- how often bar-resolution needed the m5 drilldown, and how often even
    -- that fell back to the conservative SL-assumed cases, across n_trades_taken.
    ambiguous_bar_count         INT NOT NULL DEFAULT 0,
    m5_drilldown_count          INT NOT NULL DEFAULT 0,
    m5_still_ambiguous_count    INT NOT NULL DEFAULT 0,
    m5_missing_data_count       INT NOT NULL DEFAULT 0,

    inserted_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_backtest_run (symbol, ltf_timeframe, mode, zone_source, confluence_mode,
                                 target_zone_source, period),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode)
) ENGINE=InnoDB;

-- Structural TP variant comparison (exploratory -- see
-- scripts/backtest/compare_structural_tp_variants.py module docstring for
-- the full multiple-comparisons caveat): persists the baseline vs
-- atr_stop_1.5x vs frac_0.70 vs frac_1.00 comparison run so the dashboard
-- can show it without re-running the comparison live. This is NOT a
-- second backtest_runs -- it's the side-by-side variant exploration,
-- kept in its own table specifically so it's never confused with the
-- real, adopted backtest_runs/backtest_trades results.
CREATE TABLE IF NOT EXISTS tp_variant_comparison (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol            VARCHAR(20) NOT NULL,
    ltf_timeframe     VARCHAR(10) NOT NULL,
    mode              ENUM('choch_only','choch_sweep') NOT NULL,
    variant           VARCHAR(20) NOT NULL,
    period            ENUM('full','test') NOT NULL,

    n_structural      INT NOT NULL,
    n_stop_too_tight  INT NOT NULL,
    trades_taken      INT NOT NULL,
    n_decided         INT NOT NULL,

    win_rate          DECIMAL(6,4) NULL,
    profit_factor     DECIMAL(10,4) NULL,
    expectancy_r      DECIMAL(8,4) NULL,
    max_drawdown_r    DECIMAL(10,4) NULL,
    sharpe_ratio      DECIMAL(8,4) NULL,
    deflated_sharpe_ratio DECIMAL(8,6) NULL,

    inserted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_variant (symbol, ltf_timeframe, mode, variant, period),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode)
) ENGINE=InnoDB;

-- Confluence Zone Engine (see analysis/strategies/confluence_zone_engine.py):
-- HTF (h4/h6/d1) zones formed by clustering 2+ (mode_a) or 3+ (mode_b) of
-- {OB, FVG, SwingSR, CHoCH, Sweep} factors that overlap in price and time.
-- zone_full_* is the union of every contributing factor's range;
-- zone_core_* is the intersection of the RANGED factors only (OB/FVG/
-- SwingSR), falling back to the full range when fewer than 2 ranged
-- factors contributed. confidence_score is just factor_count as "X/5" --
-- deliberately not a weighted score, per the user's request to keep it
-- interpretable. factors stores the full per-factor breakdown (type, its
-- own range or point price, formation bar) so the dashboard's planned
-- "show all contributing factors" panel extension needs no schema change.
-- status is 'active'/'invalidated' this pass (price closed through
-- zone_full_range on the wrong side); 'won'/'lost' are reserved for the
-- follow-up LTF entry-finding pass and not set here.
CREATE TABLE IF NOT EXISTS confluence_zones (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    mode               ENUM('mode_a_2factor','mode_b_3factor') NOT NULL,
    direction          ENUM('bullish','bearish') NOT NULL,

    zone_core_top      DECIMAL(16,5) NOT NULL,
    zone_core_bottom   DECIMAL(16,5) NOT NULL,
    zone_full_top      DECIMAL(16,5) NOT NULL,
    zone_full_bottom   DECIMAL(16,5) NOT NULL,

    factor_count       TINYINT     NOT NULL,
    confidence_score   VARCHAR(5)  NOT NULL,
    factors            JSON        NOT NULL,

    created_at_bar     DATETIME NOT NULL,
    last_factor_at_bar DATETIME NOT NULL,
    status             ENUM('active','invalidated','won','lost') NOT NULL DEFAULT 'active',
    resolved_at_bar    DATETIME NULL,

    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running detection over the same history must upsert, not
    -- duplicate: one zone per (symbol, timeframe, mode, direction,
    -- created_at_bar) -- two clusters of the same direction can't both
    -- form on the same bar.
    UNIQUE KEY uq_zone (symbol, timeframe, mode, direction, created_at_bar),
    INDEX idx_status (status),
    INDEX idx_created (created_at_bar DESC)
) ENGINE=InnoDB;

-- Composite Confluence Engine (see docs/DECISIONS.md "Composite Confluence
-- Engine" entries) -- ADOPTED as the production signal source despite not
-- clearing this project's own statistical floor at adoption time (real
-- track record intended to accumulate through live use, tracked here going
-- forward, rather than via another historical backfill). One row per
-- candidate scoring >= PERSIST_MIN_SCORE (2/5) AND TP1 R:R >=
-- COMPOSITE_MIN_TP1_RR -- see analysis/strategies/composite_confluence_engine.py
-- for the current production values. Candidates below PERSIST_MIN_SCORE are
-- never persisted, matching structural_tp_engine.py's "skip, don't weaken"
-- convention for its own hard floor. Rows with score in [2,3) exist ONLY to
-- back the dashboard's selectable ">=2/5, higher frequency lower quality"
-- alternate view (see docs/DECISIONS.md "threshold >=2/5 isolation test") --
-- every default/unfiltered read of this table still means score >=
-- SCORE_THRESHOLD (3/5, "qualifying"), so any ad-hoc query or report against
-- this table MUST filter by score explicitly, not assume every row qualifies.
CREATE TABLE IF NOT EXISTS composite_confluence_signals (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    ltf_timeframe      VARCHAR(10)   NOT NULL,
    direction          ENUM('bullish','bearish') NOT NULL,
    confirmed_at_bar   DATETIME NOT NULL,

    -- 6-factor composite score (0-6), equal-weight binary, each stored
    -- individually (not just the total) so the factor-presence patterns
    -- already found in real data (zone_stack/sweep near-universal,
    -- bias/choch weaker) can keep being checked as more signals accumulate,
    -- without re-deriving them from raw tables after the fact.
    score              TINYINT NOT NULL,
    f_sweep            TINYINT(1) NOT NULL,
    f_choch            TINYINT(1) NOT NULL,
    f_zone_stack       TINYINT(1) NOT NULL,
    f_crt              TINYINT(1) NOT NULL,
    f_bias             TINYINT(1) NOT NULL,
    f_div              TINYINT(1) NOT NULL,

    entry_price        DECIMAL(16,5) NOT NULL,
    stop_price         DECIMAL(16,5) NOT NULL,
    risk               DECIMAL(16,5) NOT NULL,

    -- Full ranked target ladder (TP1..TPn, whatever the real structural
    -- search found) -- same "store the full breakdown, not just the
    -- headline number" convention as confluence_zones.factors. TP1's own
    -- price/R:R are also denormalized into their own columns since TP1 is
    -- what qualification is judged against and is queried far more often
    -- than the full ladder.
    targets            JSON NOT NULL,
    tp1_price          DECIMAL(16,5) NOT NULL,
    tp1_rr             DECIMAL(8,3) NOT NULL,

    -- Which mechanism anchored this signal's candidate touch. Nested Zone
    -- Drilling replaced H1-touch as production per docs/DECISIONS.md
    -- (consistent win-rate/expectancy advantage across three comparison
    -- runs, 60d/60d-post-gate-fix/180d) -- h1_touch rows already in the
    -- table stay as historical record, never rewritten; only NEW signals
    -- going forward use nested_chain. zone_chain is NULL for h1_touch rows
    -- (no chain to show), populated for nested_chain rows so the dashboard
    -- breadcrumb can render without a join back to nested_zone_chains.
    entry_mechanism    ENUM('h1_touch','nested_chain') NOT NULL DEFAULT 'h1_touch',
    zone_chain         JSON NULL,

    -- Outcome tracking -- populated by run_composite_confluence_resolution.py
    -- as real price history accumulates past confirmed_at_bar, reusing
    -- structural_backtest_engine.py's own walk-forward/ambiguous-bar
    -- resolution exactly as the baseline system does, judged against TP1
    -- (the qualifying target) same as the hard R:R rule this signal was
    -- accepted under. NULL until resolved; 'open' rows are the live,
    -- growing sample this table exists to accumulate.
    exit_reason        ENUM('open','win','loss') NOT NULL DEFAULT 'open',
    exit_bar_datetime  DATETIME NULL,
    resolution_method  ENUM('m15_clean','m5_drilldown','m5_still_ambiguous_sl_assumed',
                             'm5_data_missing_sl_assumed','m5_no_subbar_breach_sl_assumed') NULL,
    r_outcome          DECIMAL(8,3) NULL,

    -- Human-in-the-loop fields (see docs/DECISIONS.md "backend review"
    -- entry) -- deliberately nullable free-form columns, not another
    -- detection output: the trader using this system daily can record
    -- whether they actually took the signal and why, independent of what
    -- the mechanical TP1/SL outcome above ends up being. This is the
    -- concrete hook the review asked for, not a placeholder.
    user_action        ENUM('taken','skipped','modified') NULL,
    user_note          VARCHAR(1000) NULL,

    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- entry_price/stop_price/target ranking are all fully determined by
    -- (symbol, direction, confirmed_at_bar) alone -- confirmed empirically
    -- during design validation, multiple distinct zones touched at the
    -- same bar always resolve to the identical signal -- so this triple is
    -- sufficient to prevent duplicates without needing a source-zone id.
    UNIQUE KEY uq_composite_signal (symbol, ltf_timeframe, direction, confirmed_at_bar),
    INDEX idx_exit_reason (symbol, exit_reason),
    INDEX idx_confirmed (confirmed_at_bar DESC)
) ENGINE=InnoDB;

-- Nested Zone Drilling (see docs/DECISIONS.md, analysis/strategies/
-- nested_zone_engine.py) -- kept as SEPARATE tables from smc_signals, not
-- merged into it: smc_signals means "the HTF layer" everywhere else in
-- this project (e.g. the composite engine's zone_stack query explicitly
-- filters timeframe IN ('h1','h4','h6','d1')), and mixing in churny,
-- short-lived M15/M5 zones risks silently leaking into HTF-only consumers.
CREATE TABLE IF NOT EXISTS ltf_smc_zones (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,  -- m15 or m5 only
    zone_type          ENUM('order_block_bullish','order_block_bearish',
                             'fvg_bullish','fvg_bearish',
                             'swing_resistance','swing_support') NOT NULL,
    zone_top           DECIMAL(16,5) NOT NULL,
    zone_bottom        DECIMAL(16,5) NOT NULL,
    state              ENUM('active','mitigated','invalidated') NOT NULL DEFAULT 'active',
    created_at_bar     DATETIME NOT NULL,
    mitigated_at_bar   DATETIME NULL,
    invalidated_at_bar DATETIME NULL,
    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ltf_zone (symbol, timeframe, zone_type, zone_top, zone_bottom, created_at_bar),
    INDEX idx_symbol_tf (symbol, timeframe)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS nested_zone_chains (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol              VARCHAR(20)   NOT NULL,
    direction           ENUM('bullish','bearish') NOT NULL,
    root_timeframe      VARCHAR(10)   NOT NULL,
    terminal_timeframe  VARCHAR(10)   NOT NULL,  -- m15 or m5

    -- Ordered list of every level that actually contributed a zone (an
    -- intermediate HTF level with no valid nested zone is skipped, not
    -- recorded as a gap) -- each entry: {timeframe, zone_type, zone_top,
    -- zone_bottom, created_at_bar, state}. Dashboard breadcrumb (e.g.
    -- "D1 zone -> H4 FVG -> H1 swing -> M15 swing -> entry") reads this
    -- directly, same "store the full breakdown" convention as
    -- confluence_zones.factors / composite_confluence_signals.targets.
    chain               JSON NOT NULL,

    -- Terminal (finest) zone's own bounds, denormalized for the entry/stop
    -- computation that consumes this row as an h1_zones-shaped candidate.
    zone_type           ENUM('order_block_bullish','order_block_bearish',
                              'fvg_bullish','fvg_bearish',
                              'swing_resistance','swing_support') NOT NULL,
    zone_top            DECIMAL(16,5) NOT NULL,
    zone_bottom         DECIMAL(16,5) NOT NULL,
    created_at_bar      DATETIME NOT NULL,
    invalidated_at_bar  DATETIME NULL,

    inserted_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_chain (symbol, terminal_timeframe, zone_type, zone_top, zone_bottom, created_at_bar),
    INDEX idx_symbol_created (symbol, created_at_bar DESC)
) ENGINE=InnoDB;

CREATE DATABASE IF NOT EXISTS curated_eurusd
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE curated_eurusd;

GRANT ALL PRIVILEGES ON curated_eurusd.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS smc_signals (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    zone_type          ENUM('order_block_bullish','order_block_bearish',
                             'fvg_bullish','fvg_bearish',
                             'swing_resistance','swing_support') NOT NULL,
    zone_top           DECIMAL(16,5) NOT NULL,
    zone_bottom        DECIMAL(16,5) NOT NULL,
    state              ENUM('active','mitigated','invalidated') NOT NULL DEFAULT 'active',
    created_at_bar     DATETIME NOT NULL,
    mitigated_at_bar   DATETIME NULL,
    invalidated_at_bar DATETIME NULL,
    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_zone (symbol, timeframe, zone_type, created_at_bar),
    INDEX idx_state (symbol, timeframe, state),
    INDEX idx_created (created_at_bar DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS crt_signals (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    signal_type        ENUM('asian_range_high','asian_range_low','equilibrium') NOT NULL,
    session_date       DATE NULL,
    bar_datetime       DATETIME NOT NULL,
    level_price        DECIMAL(16,5) NULL,
    range_high         DECIMAL(16,5) NULL,
    range_low          DECIMAL(16,5) NULL,
    equilibrium_price  DECIMAL(16,5) NULL,
    zone_bias          ENUM('premium','discount') NULL,
    state              ENUM('pending','swept','expired') NULL,
    sweep_direction    ENUM('bullish','bearish') NULL,
    swept_at_bar       DATETIME NULL,
    expired_at_bar     DATETIME NULL,
    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_crt_signal (symbol, timeframe, signal_type, bar_datetime),
    INDEX idx_state (symbol, timeframe, state),
    INDEX idx_bar (bar_datetime DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS liquidity_sweeps (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    sweep_type         ENUM('bsl','ssl') NOT NULL,
    direction          ENUM('bullish','bearish') NOT NULL,
    swept_level_price  DECIMAL(16,5) NOT NULL,
    bar_datetime       DATETIME NOT NULL,
    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_sweep (symbol, timeframe, sweep_type, bar_datetime),
    INDEX idx_bar (symbol, timeframe, bar_datetime DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS features (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    bar_datetime       DATETIME NOT NULL,
    ema_20             DECIMAL(16,5) NULL,
    ema_50             DECIMAL(16,5) NULL,
    ema_200            DECIMAL(16,5) NULL,
    atr_14             DECIMAL(16,6) NULL,
    rsi_14             DECIMAL(8,3)  NULL,
    obv                DECIMAL(24,4) NULL,
    stoch_k            DECIMAL(8,3)  NULL,
    stoch_d            DECIMAL(8,3)  NULL,
    cci_20             DECIMAL(10,3) NULL,
    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_feature_bar (symbol, timeframe, bar_datetime),
    INDEX idx_bar (bar_datetime DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS volume_profile (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                VARCHAR(20)   NOT NULL,
    timeframe             VARCHAR(10)   NOT NULL,
    session_date          DATE NOT NULL,
    bin_index             SMALLINT NOT NULL,
    bin_low               DECIMAL(16,5) NOT NULL,
    bin_high              DECIMAL(16,5) NOT NULL,
    bin_center            DECIMAL(16,5) NOT NULL,
    bin_volume            DECIMAL(20,4) NOT NULL,
    is_poc                BOOLEAN NOT NULL DEFAULT FALSE,
    in_value_area         BOOLEAN NOT NULL DEFAULT FALSE,
    is_hvn                BOOLEAN NOT NULL DEFAULT FALSE,
    is_lvn                BOOLEAN NOT NULL DEFAULT FALSE,
    session_poc           DECIMAL(16,5) NOT NULL,
    session_vah           DECIMAL(16,5) NOT NULL,
    session_val           DECIMAL(16,5) NOT NULL,
    session_total_volume  DECIMAL(20,4) NOT NULL,
    num_bins              SMALLINT NOT NULL,
    inserted_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_vp_bin (symbol, timeframe, session_date, bin_index),
    INDEX idx_session (symbol, timeframe, session_date),
    INDEX idx_poc (symbol, timeframe, is_poc)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS divergence_signals (
    id                     BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                 VARCHAR(20)   NOT NULL,
    timeframe              VARCHAR(10)   NOT NULL,
    bar_datetime           DATETIME NOT NULL,
    divergence_type        VARCHAR(20)   NOT NULL,
    divergence_class       ENUM('regular','hidden') NOT NULL,
    direction              ENUM('bullish','bearish') NOT NULL,
    prev_pivot_datetime    DATETIME NOT NULL,
    prev_pivot_price       DECIMAL(16,5) NOT NULL,
    prev_pivot_indicator   DECIMAL(24,4) NOT NULL,
    curr_pivot_datetime    DATETIME NOT NULL,
    curr_pivot_price       DECIMAL(16,5) NOT NULL,
    curr_pivot_indicator   DECIMAL(24,4) NOT NULL,
    inserted_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_divergence (symbol, timeframe, divergence_type, divergence_class, curr_pivot_datetime),
    INDEX idx_bar (symbol, timeframe, bar_datetime DESC),
    INDEX idx_direction (symbol, timeframe, divergence_type, divergence_class, direction)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS htf_bias (
    id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                   VARCHAR(20)   NOT NULL,
    timeframe                VARCHAR(10)   NOT NULL,
    bar_datetime             DATETIME NOT NULL,
    bias                     ENUM('bullish','bearish','neutral') NOT NULL,
    confluence_score         DECIMAL(6,2) NOT NULL,
    raw_score_before_caution DECIMAL(6,2) NOT NULL,
    smc_contribution         DECIMAL(6,2) NOT NULL,
    smc_active_bullish_zones SMALLINT NOT NULL,
    smc_active_bearish_zones SMALLINT NOT NULL,
    crt_contribution         DECIMAL(6,2) NOT NULL,
    crt_equilibrium_bias     ENUM('premium','discount') NULL,
    indicator_contribution      DECIMAL(6,2) NOT NULL,
    volume_profile_contribution DECIMAL(6,2) NOT NULL,
    hidden_divergence_contribution DECIMAL(6,2) NOT NULL,
    hidden_divergence_count        SMALLINT NOT NULL,
    regular_divergence_caution_factor DECIMAL(5,4) NOT NULL,
    regular_divergence_count          SMALLINT NOT NULL,
    liquidity_sweep_contribution DECIMAL(6,2) NOT NULL,
    liquidity_sweep_direction    ENUM('bullish','bearish') NULL,
    session              ENUM('asian','london','ny','killzone') NOT NULL,
    session_multiplier   DECIMAL(4,3) NOT NULL,
    inserted_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_bias_bar (symbol, timeframe, bar_datetime),
    INDEX idx_bias (symbol, timeframe, bias),
    INDEX idx_bar (bar_datetime DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ltf_trigger_signals (
    id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                   VARCHAR(20)   NOT NULL,
    ltf_timeframe            VARCHAR(10)   NOT NULL,
    mode                     ENUM('choch_only','choch_sweep') NOT NULL,
    direction                ENUM('bullish','bearish') NOT NULL,

    -- 'confluence_bullish_mode_a'/'_mode_b' and 'confluence_bearish_mode_a'/
    -- '_mode_b' cover triggers sourced from confluence_zones (multi-factor,
    -- no single zone_type of its own) -- see zone_source/confluence_zone_id
    -- below for how those are told apart from single-factor smc_signals
    -- triggers. The confluence_mode is baked into this value (not left to
    -- direction alone) because a mode_b_3factor zone is BY DEFINITION also
    -- a mode_a_2factor zone of the same underlying cluster (same
    -- last_factor_at_bar) -- a direction-only value made uq_trigger below
    -- unable to tell the two modes' triggers apart, and MySQL's ON
    -- DUPLICATE KEY UPDATE silently merged one mode's rows into the
    -- other's (see docs/DECISIONS.md).
    htf_zone_type            ENUM('order_block_bullish','order_block_bearish',
                                   'fvg_bullish','fvg_bearish',
                                   'swing_resistance','swing_support',
                                   'confluence_bullish_mode_a','confluence_bullish_mode_b',
                                   'confluence_bearish_mode_a','confluence_bearish_mode_b') NOT NULL,
    htf_zone_top             DECIMAL(16,5) NOT NULL,
    htf_zone_bottom          DECIMAL(16,5) NOT NULL,
    htf_zone_created_at_bar  DATETIME NOT NULL,

    -- Confluence Zone Engine LTF entry-finding pass (see
    -- analysis/strategies/confluence_ltf_trigger.py): zone_source
    -- distinguishes this row's HTF zone origin. confluence_zone_id is a
    -- soft FK into confluence_zones.id (NULL for smc_signals-sourced
    -- rows). confluence_mode mirrors confluence_zones.mode (NULL unless
    -- zone_source='confluence_zone'). zone_range_used records whether
    -- htf_zone_top/htf_zone_bottom above hold the confluence zone's
    -- CORE range (entry confirmed inside the multi-factor overlap --
    -- tighter stop) or its FULL range (confirmed only inside the union,
    -- same behavior as a single-factor zone) -- see module docstring for
    -- the full core-first-fallback-to-full selection rule.
    zone_source              ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    confluence_zone_id       BIGINT NULL,
    confluence_mode          ENUM('mode_a_2factor','mode_b_3factor') NULL,
    zone_range_used          ENUM('full','core') NULL,

    -- Confluence-aware target selection (see docs/DECISIONS.md, target-
    -- selection fix pass): whether the opposing-zone search below read
    -- smc_signals single-factor zones (original behavior, default) or
    -- confluence_zones of the SAME mode as this trigger's own entry zone.
    -- A second, orthogonal dimension from zone_source above -- a
    -- confluence-sourced ENTRY can be tested with either target source,
    -- which is exactly the controlled A/B this pass needed (same entry,
    -- only the target side varies). Included in both unique keys below so
    -- the two target variants persist as separate rows, not overwrite
    -- each other.
    target_zone_source       ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',

    touch_bar_datetime       DATETIME NOT NULL,
    choch_bar_datetime       DATETIME NOT NULL,
    -- choch_sweep only; NULL for choch_only.
    sweep_bar_datetime       DATETIME NULL,
    sweep_type               ENUM('bsl','ssl') NULL,

    -- max(touch, choch, sweep) -- the bar at which every required
    -- condition first became simultaneously true, i.e. the actual
    -- actionable moment a live system would have produced this signal at.
    confirmed_at_bar         DATETIME NOT NULL,

    -- Structural TP (Option 2, confirmed with the user over Options 1/3 --
    -- fewest tunable parameters given <2yr of one-directional history): TP
    -- is not a chosen ratio, it's read off the nearest active OPPOSING zone
    -- ahead of price -- see analysis/strategies/structural_tp_engine.py.
    -- entry_price = LTF close at confirmed_at_bar. stop_price = the far
    -- edge of the trigger's OWN htf_zone (htf_zone_bottom for bullish,
    -- htf_zone_top for bearish) -- the natural invalidation point. The
    -- opposing zone lookup is causal: only zones with created_at_bar <=
    -- confirmed_at_bar and not yet invalidated as of confirmed_at_bar are
    -- eligible, same active-window pattern as htf_bias/zone queries
    -- elsewhere. target_price sits STRUCTURAL_TP_FRACTION (0.85, flagged
    -- unvalidated same as CONFIRMATION_WINDOW_BARS) of the way from entry
    -- to the opposing zone's near edge, not the full distance. structural_rr
    -- is computed directly from entry/stop/target, never chosen.
    -- target_status='no_opposing_zone' when no eligible opposing zone
    -- exists (fallback = skip, not a default R:R -- see engine module
    -- docstring for why) -- target/rr columns stay NULL in that case, and
    -- the row is excluded from any backtest requiring a TP.
    -- target_status='invalid_geometry' covers the (should be rare)
    -- edge case where entry_price has already breached the stop.
    entry_price              DECIMAL(16,5) NULL,
    stop_price                DECIMAL(16,5) NULL,
    -- 'confluence_bullish'/'confluence_bearish' cover a confluence-zone
    -- opposing wall (target_zone_source='confluence_zone') -- unlike
    -- htf_zone_type, mode doesn't need to be baked in here since
    -- opposing_zone_type isn't part of any unique key.
    opposing_zone_type       ENUM('order_block_bullish','order_block_bearish',
                                   'fvg_bullish','fvg_bearish',
                                   'swing_resistance','swing_support',
                                   'confluence_bullish','confluence_bearish') NULL,
    opposing_zone_top        DECIMAL(16,5) NULL,
    opposing_zone_bottom     DECIMAL(16,5) NULL,
    target_price             DECIMAL(16,5) NULL,
    structural_rr            DECIMAL(8,3) NULL,
    target_status            ENUM('structural','no_opposing_zone','invalid_geometry','stop_too_tight') NULL,

    inserted_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Re-running detection over the same history must upsert, not
    -- duplicate: one row per distinct (zone, touch, choch, target source)
    -- confirmation.
    UNIQUE KEY uq_trigger (symbol, ltf_timeframe, mode, htf_zone_type,
                            htf_zone_created_at_bar, touch_bar_datetime, choch_bar_datetime,
                            target_zone_source),
    -- Extra safety net for confluence-sourced rows, on top of htf_zone_type
    -- now encoding confluence_mode (see that column's comment): two
    -- DIFFERENT confluence zones of the same direction/mode that happen to
    -- share both a created_at_bar (last_factor_at_bar) and a touch/CHoCH
    -- bar (real, observed in practice when zones overlap in price) would
    -- still incorrectly collide under uq_trigger alone. confluence_zone_id
    -- disambiguates them directly; it's NULL for smc_signals-sourced rows,
    -- which MySQL's NULL-is-never-equal unique-index semantics correctly
    -- exempt from this key (they're already covered by uq_trigger above).
    UNIQUE KEY uq_trigger_confluence (symbol, ltf_timeframe, mode, confluence_zone_id,
                                       touch_bar_datetime, choch_bar_datetime, target_zone_source),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode),
    INDEX idx_confirmed (confirmed_at_bar DESC)
) ENGINE=InnoDB;

-- Structural Backtest (Pass 3 of strategies/): turns confirmed LTF trigger
-- signals with a valid structural TP into an actual simulated trade
-- sequence. See analysis/backtester/structural_backtest_engine.py and
-- analysis/backtester/deflated_sharpe.py module docstrings for the full
-- design: one-trade-at-a-time per (symbol, ltf_timeframe, mode) matching
-- the fixed-0.01-lot single-account context, ambiguous same-bar SL/TP
-- resolved via m5 drilldown (conservative SL-first fallback when even that
-- is ambiguous or unavailable), no artificial max holding period, and a
-- Deflated Sharpe Ratio (Bailey & Lopez de Prado) computed against the
-- Mode A vs Mode B comparison as the trial set -- see that module's
-- docstring for the explicit limitations of that N=2 estimate.
-- backtest_trades: one row per trade ACTUALLY TAKEN (signals skipped for
-- overlap never appear here -- see backtest_runs.n_trades_skipped_overlap
-- for that count). running_equity_r lets the equity curve be reconstructed
-- by ORDER BY entry_bar_datetime without re-deriving it from r_outcome.
CREATE TABLE IF NOT EXISTS backtest_trades (
    id                    BIGINT AUTO_INCREMENT PRIMARY KEY,
    -- Soft FK into ltf_trigger_signals.id -- the exact trigger this
    -- trade came from. Required as the disambiguator in uq_backtest_trade
    -- below now that concurrent trades are allowed: two different HTF
    -- zones can genuinely share the same entry_bar_datetime, so that
    -- column alone is no longer a unique identifier for a trade. Added
    -- after older confluence-zone backtest rows already existed (see
    -- docs/DECISIONS.md) -- those specific pre-existing rows were
    -- backfilled with their own backtest_trades.id (NOT a genuine link
    -- to ltf_trigger_signals for that older slice) purely to satisfy
    -- this key; every row inserted from this schema version onward
    -- carries the real source trigger id.
    source_trigger_id     BIGINT NOT NULL,
    symbol                VARCHAR(20)   NOT NULL,
    ltf_timeframe         VARCHAR(10)   NOT NULL,
    mode                  ENUM('choch_only','choch_sweep') NOT NULL,
    -- Confluence LTF Trigger backtest (see docs/DECISIONS.md): zone_source
    -- distinguishes which ltf_trigger_signals pool this trade's entry came
    -- from. confluence_mode uses an explicit 'none' sentinel rather than
    -- NULL for smc_signals-sourced rows -- NULL would break
    -- uq_backtest_trade's uniqueness guarantee for those rows (MySQL never
    -- treats two NULLs as equal in a unique index), and mode_a_2factor vs
    -- mode_b_3factor runs for the SAME underlying cluster can genuinely
    -- share an entry_bar_datetime (a mode_b zone is always also a mode_a
    -- zone of the same cluster), so this dimension must be a real,
    -- comparable value in the key, not nullable.
    zone_source           ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    confluence_mode        ENUM('none','mode_a_2factor','mode_b_3factor') NOT NULL DEFAULT 'none',
    -- Mirrors ltf_trigger_signals.target_zone_source -- which opposing-zone
    -- pool produced this trade's target_price. Orthogonal to zone_source
    -- above (a confluence-sourced entry can pair with either target
    -- source), included in uq_backtest_trade below for the same reason.
    target_zone_source     ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    direction             ENUM('bullish','bearish') NOT NULL,

    entry_bar_datetime    DATETIME NOT NULL,
    entry_price           DECIMAL(16,5) NOT NULL,
    stop_price            DECIMAL(16,5) NOT NULL,
    target_price          DECIMAL(16,5) NOT NULL,
    structural_rr         DECIMAL(8,3) NOT NULL,

    htf_zone_type         ENUM('order_block_bullish','order_block_bearish',
                                'fvg_bullish','fvg_bearish',
                                'swing_resistance','swing_support',
                                'confluence_bullish_mode_a','confluence_bullish_mode_b',
                                'confluence_bearish_mode_a','confluence_bearish_mode_b') NOT NULL,
    htf_zone_top          DECIMAL(16,5) NOT NULL,
    htf_zone_bottom       DECIMAL(16,5) NOT NULL,

    -- NULL exit_bar_datetime/bars_held/r_outcome only for exit_reason='open_at_data_end'.
    exit_bar_datetime     DATETIME NULL,
    exit_reason           ENUM('win','loss','open_at_data_end') NOT NULL,
    bars_held             INT NULL,
    resolution_method     ENUM('m15_clean','m5_drilldown','m5_still_ambiguous_sl_assumed',
                                'm5_data_missing_sl_assumed','m5_no_subbar_breach_sl_assumed',
                                'open_at_data_end') NOT NULL,
    r_outcome             DECIMAL(8,3) NULL,
    running_equity_r      DECIMAL(10,3) NULL,

    inserted_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- A full re-simulation deletes and re-inserts all rows for a
    -- (symbol, ltf_timeframe, mode, zone_source, confluence_mode) rather
    -- than upserting -- the trade count itself can change between runs if
    -- upstream logic changes, and an upsert-only script would leave stale
    -- orphaned rows (the exact class of bug this project has been bitten
    -- by before).
    UNIQUE KEY uq_backtest_trade (symbol, ltf_timeframe, mode, zone_source, confluence_mode,
                                   target_zone_source, source_trigger_id),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode),
    INDEX idx_entry (entry_bar_datetime DESC)
) ENGINE=InnoDB;

-- backtest_runs: one row per (symbol, ltf_timeframe, mode, period), period
-- in {'full','test'} -- 'test' is the held-out ~30% (by calendar time, not
-- trade count) of history never looked at until final evaluation; 'full'
-- covers everything. Both are computed from the SAME single chronological
-- trade simulation (see script), sliced by entry_bar_datetime >=
-- oos_cutoff_date for 'test' -- not a separate re-simulation restarting
-- position state at the cutoff, since a real account could carry an
-- in-sample-opened position across that boundary.
CREATE TABLE IF NOT EXISTS backtest_runs (
    id                          BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol                      VARCHAR(20) NOT NULL,
    ltf_timeframe               VARCHAR(10) NOT NULL,
    mode                        ENUM('choch_only','choch_sweep') NOT NULL,
    -- Same zone_source/confluence_mode dimension and 'none'-sentinel
    -- reasoning as backtest_trades above.
    zone_source                 ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    confluence_mode              ENUM('none','mode_a_2factor','mode_b_3factor') NOT NULL DEFAULT 'none',
    target_zone_source           ENUM('smc_signals','confluence_zone') NOT NULL DEFAULT 'smc_signals',
    period                      ENUM('full','test') NOT NULL,

    period_start                DATETIME NOT NULL,
    period_end                  DATETIME NOT NULL,
    oos_cutoff_date             DATETIME NOT NULL,

    n_signals_structural        INT NOT NULL,
    n_trades_taken               INT NOT NULL,
    n_trades_skipped_overlap    INT NOT NULL,
    n_wins                      INT NOT NULL,
    n_losses                    INT NOT NULL,
    n_open_at_data_end          INT NOT NULL,

    win_rate                    DECIMAL(6,4) NULL,
    profit_factor               DECIMAL(10,4) NULL,
    expectancy_r                DECIMAL(8,4) NULL,
    max_drawdown_r              DECIMAL(10,4) NULL,

    -- Sharpe here is a per-TRADE (not time-annualized) ratio -- see
    -- deflated_sharpe.py module docstring for why. n_trials_for_dsr and
    -- sr_variance_across_trials are the DSR's selection-bias inputs
    -- (N=2: this mode's Sharpe vs the OTHER mode's Sharpe for the same
    -- symbol/period, an explicitly-flagged rough estimate -- see that
    -- module's docstring for the full limitation).
    sharpe_ratio                DECIMAL(8,4) NULL,
    skewness                    DECIMAL(8,4) NULL,
    kurtosis                    DECIMAL(8,4) NULL,
    n_trials_for_dsr            SMALLINT NULL,
    sr_variance_across_trials   DECIMAL(10,6) NULL,
    sr0_threshold               DECIMAL(8,4) NULL,
    deflated_sharpe_ratio       DECIMAL(8,6) NULL,
    psr_vs_zero                 DECIMAL(8,6) NULL,

    -- ~200 trades/12 months floor discussed early in this project, scaled
    -- to this row's own period_start/period_end duration.
    min_sample_floor_required   INT NULL,
    meets_min_sample_floor      BOOLEAN NULL,

    -- Outcome-resolution diagnostics (see structural_backtest_engine.py):
    -- how often bar-resolution needed the m5 drilldown, and how often even
    -- that fell back to the conservative SL-assumed cases, across n_trades_taken.
    ambiguous_bar_count         INT NOT NULL DEFAULT 0,
    m5_drilldown_count          INT NOT NULL DEFAULT 0,
    m5_still_ambiguous_count    INT NOT NULL DEFAULT 0,
    m5_missing_data_count       INT NOT NULL DEFAULT 0,

    inserted_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_backtest_run (symbol, ltf_timeframe, mode, zone_source, confluence_mode,
                                 target_zone_source, period),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode)
) ENGINE=InnoDB;

-- Structural TP variant comparison (exploratory -- see
-- scripts/backtest/compare_structural_tp_variants.py module docstring for
-- the full multiple-comparisons caveat): persists the baseline vs
-- atr_stop_1.5x vs frac_0.70 vs frac_1.00 comparison run so the dashboard
-- can show it without re-running the comparison live. This is NOT a
-- second backtest_runs -- it's the side-by-side variant exploration,
-- kept in its own table specifically so it's never confused with the
-- real, adopted backtest_runs/backtest_trades results.
CREATE TABLE IF NOT EXISTS tp_variant_comparison (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol            VARCHAR(20) NOT NULL,
    ltf_timeframe     VARCHAR(10) NOT NULL,
    mode              ENUM('choch_only','choch_sweep') NOT NULL,
    variant           VARCHAR(20) NOT NULL,
    period            ENUM('full','test') NOT NULL,

    n_structural      INT NOT NULL,
    n_stop_too_tight  INT NOT NULL,
    trades_taken      INT NOT NULL,
    n_decided         INT NOT NULL,

    win_rate          DECIMAL(6,4) NULL,
    profit_factor     DECIMAL(10,4) NULL,
    expectancy_r      DECIMAL(8,4) NULL,
    max_drawdown_r    DECIMAL(10,4) NULL,
    sharpe_ratio      DECIMAL(8,4) NULL,
    deflated_sharpe_ratio DECIMAL(8,6) NULL,

    inserted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_variant (symbol, ltf_timeframe, mode, variant, period),
    INDEX idx_symbol_mode (symbol, ltf_timeframe, mode)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS confluence_zones (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,
    mode               ENUM('mode_a_2factor','mode_b_3factor') NOT NULL,
    direction          ENUM('bullish','bearish') NOT NULL,

    zone_core_top      DECIMAL(16,5) NOT NULL,
    zone_core_bottom   DECIMAL(16,5) NOT NULL,
    zone_full_top      DECIMAL(16,5) NOT NULL,
    zone_full_bottom   DECIMAL(16,5) NOT NULL,

    factor_count       TINYINT     NOT NULL,
    confidence_score   VARCHAR(5)  NOT NULL,
    factors            JSON        NOT NULL,

    created_at_bar     DATETIME NOT NULL,
    last_factor_at_bar DATETIME NOT NULL,
    status             ENUM('active','invalidated','won','lost') NOT NULL DEFAULT 'active',
    resolved_at_bar    DATETIME NULL,

    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_zone (symbol, timeframe, mode, direction, created_at_bar),
    INDEX idx_status (status),
    INDEX idx_created (created_at_bar DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS composite_confluence_signals (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    ltf_timeframe      VARCHAR(10)   NOT NULL,
    direction          ENUM('bullish','bearish') NOT NULL,
    confirmed_at_bar   DATETIME NOT NULL,

    score              TINYINT NOT NULL,
    f_sweep            TINYINT(1) NOT NULL,
    f_choch            TINYINT(1) NOT NULL,
    f_zone_stack       TINYINT(1) NOT NULL,
    f_crt              TINYINT(1) NOT NULL,
    f_bias             TINYINT(1) NOT NULL,
    f_div              TINYINT(1) NOT NULL,

    entry_price        DECIMAL(16,5) NOT NULL,
    stop_price         DECIMAL(16,5) NOT NULL,
    risk               DECIMAL(16,5) NOT NULL,

    targets            JSON NOT NULL,
    tp1_price          DECIMAL(16,5) NOT NULL,
    tp1_rr             DECIMAL(8,3) NOT NULL,

    -- Which mechanism anchored this signal's candidate touch. Nested Zone
    -- Drilling replaced H1-touch as production per docs/DECISIONS.md
    -- (consistent win-rate/expectancy advantage across three comparison
    -- runs, 60d/60d-post-gate-fix/180d) -- h1_touch rows already in the
    -- table stay as historical record, never rewritten; only NEW signals
    -- going forward use nested_chain. zone_chain is NULL for h1_touch rows
    -- (no chain to show), populated for nested_chain rows so the dashboard
    -- breadcrumb can render without a join back to nested_zone_chains.
    entry_mechanism    ENUM('h1_touch','nested_chain') NOT NULL DEFAULT 'h1_touch',
    zone_chain         JSON NULL,

    exit_reason        ENUM('open','win','loss') NOT NULL DEFAULT 'open',
    exit_bar_datetime  DATETIME NULL,
    resolution_method  ENUM('m15_clean','m5_drilldown','m5_still_ambiguous_sl_assumed',
                             'm5_data_missing_sl_assumed','m5_no_subbar_breach_sl_assumed') NULL,
    r_outcome          DECIMAL(8,3) NULL,

    user_action        ENUM('taken','skipped','modified') NULL,
    user_note          VARCHAR(1000) NULL,

    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uq_composite_signal (symbol, ltf_timeframe, direction, confirmed_at_bar),
    INDEX idx_exit_reason (symbol, exit_reason),
    INDEX idx_confirmed (confirmed_at_bar DESC)
) ENGINE=InnoDB;

-- Nested Zone Drilling (see docs/DECISIONS.md, analysis/strategies/
-- nested_zone_engine.py) -- kept as SEPARATE tables from smc_signals, not
-- merged into it: smc_signals means "the HTF layer" everywhere else in
-- this project (e.g. the composite engine's zone_stack query explicitly
-- filters timeframe IN ('h1','h4','h6','d1')), and mixing in churny,
-- short-lived M15/M5 zones risks silently leaking into HTF-only consumers.
CREATE TABLE IF NOT EXISTS ltf_smc_zones (
    id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol             VARCHAR(20)   NOT NULL,
    timeframe          VARCHAR(10)   NOT NULL,  -- m15 or m5 only
    zone_type          ENUM('order_block_bullish','order_block_bearish',
                             'fvg_bullish','fvg_bearish',
                             'swing_resistance','swing_support') NOT NULL,
    zone_top           DECIMAL(16,5) NOT NULL,
    zone_bottom        DECIMAL(16,5) NOT NULL,
    state              ENUM('active','mitigated','invalidated') NOT NULL DEFAULT 'active',
    created_at_bar     DATETIME NOT NULL,
    mitigated_at_bar   DATETIME NULL,
    invalidated_at_bar DATETIME NULL,
    inserted_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_ltf_zone (symbol, timeframe, zone_type, zone_top, zone_bottom, created_at_bar),
    INDEX idx_symbol_tf (symbol, timeframe)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS nested_zone_chains (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    symbol              VARCHAR(20)   NOT NULL,
    direction           ENUM('bullish','bearish') NOT NULL,
    root_timeframe      VARCHAR(10)   NOT NULL,
    terminal_timeframe  VARCHAR(10)   NOT NULL,  -- m15 or m5

    -- Ordered list of every level that actually contributed a zone (an
    -- intermediate HTF level with no valid nested zone is skipped, not
    -- recorded as a gap) -- each entry: {timeframe, zone_type, zone_top,
    -- zone_bottom, created_at_bar, state}. Dashboard breadcrumb (e.g.
    -- "D1 zone -> H4 FVG -> H1 swing -> M15 swing -> entry") reads this
    -- directly, same "store the full breakdown" convention as
    -- confluence_zones.factors / composite_confluence_signals.targets.
    chain               JSON NOT NULL,

    -- Terminal (finest) zone's own bounds, denormalized for the entry/stop
    -- computation that consumes this row as an h1_zones-shaped candidate.
    zone_type           ENUM('order_block_bullish','order_block_bearish',
                              'fvg_bullish','fvg_bearish',
                              'swing_resistance','swing_support') NOT NULL,
    zone_top            DECIMAL(16,5) NOT NULL,
    zone_bottom         DECIMAL(16,5) NOT NULL,
    created_at_bar      DATETIME NOT NULL,
    invalidated_at_bar  DATETIME NULL,

    inserted_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_chain (symbol, terminal_timeframe, zone_type, zone_top, zone_bottom, created_at_bar),
    INDEX idx_symbol_created (symbol, created_at_bar DESC)
) ENGINE=InnoDB;
