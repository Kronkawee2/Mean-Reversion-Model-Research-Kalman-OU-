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
