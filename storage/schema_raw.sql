-- ============================================================
-- Step 1 (Raw Data) — Raw schema.
-- Grouped by symbol: each symbol = 1 database (raw_gold, raw_eurusd, raw_dxy,
-- raw_us10y, raw_vix, raw_gdx) plus pipeline_status for sync-freshness checks.
-- Step 3 (trade_signals, backtest_runs, equity_curve) lives in
-- schema_mart.sql, not here — see that file for why it was split out.
-- Phase 2i slice: raw_cot (CFTC COT Legacy report, weekly, gold+EUR — see
-- fetcher/cot_fetcher.py) and raw_spdr (SPDR GLD daily holdings — see
-- fetcher/spdr_fetcher.py), added for the final 2 divergence models
-- (COT, SPDR holdings). Neither is OHLCV-shaped like the tables above,
-- so their tables have their own columns rather than reusing the
-- price/volume shape.
-- ============================================================
-- ── GOLD Database ────────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS raw_gold
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_gold;

-- MYSQL_USER (see docker-compose.yml, driven by DB_USER in .env) only gets
-- privileges on MYSQL_DATABASE by default. mt5_sync_service.py and other
-- Step 1 writers connect directly to `raw_gold`, so grant it explicitly here.
-- Hardcoded to 'quant_user' to match the current .env DB_USER — update this
-- if DB_USER ever changes. The user itself already exists by the time this
-- script runs (MYSQL_USER is provisioned by the base entrypoint before
-- docker-entrypoint-initdb.d/*.sql executes).
GRANT ALL PRIVILEGES ON raw_gold.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS m5 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo',
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS m15 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo',
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS h1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo',
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS h4 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS h6 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS d1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

-- Legacy processed-layer table (rsi_14/sma/ema/macd/bb columns) predating
-- this project's raw/curated/mart layer rework. Left as-is in this pass —
-- not decided on yet; see schema_curated.sql's smc_signals/crt_signals/
-- features tables for where this kind of content lives going forward.
CREATE TABLE IF NOT EXISTS signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    signal_date DATE NOT NULL,
    signal_datetime DATETIME NOT NULL,
    signal_type VARCHAR(50) NOT NULL,
    signal_value DECIMAL(12, 4),
    signal_label VARCHAR(20) NOT NULL,
    description TEXT,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_signal (signal_datetime, signal_type),
    INDEX idx_date (signal_date DESC),
    INDEX idx_label (signal_label)
) ENGINE=InnoDB;

-- Legacy processed-layer table (rsi_14/sma/ema/macd/bb columns) predating
-- this project's raw/curated/mart layer rework. Left as-is in this pass —
-- not decided on yet; see schema_curated.sql's smc_signals/crt_signals/
-- features tables for where this kind of content lives going forward.
CREATE TABLE IF NOT EXISTS daily_summary (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    summary_date DATE NOT NULL,
    open_price DECIMAL(16, 5),
    close_price DECIMAL(16, 5),
    high_price DECIMAL(16, 5),
    low_price DECIMAL(16, 5),
    price_change DECIMAL(16, 5),
    price_change_pct DECIMAL(8, 4),
    volume BIGINT DEFAULT 0,
    rsi_14 DECIMAL(8, 4),
    sma_20 DECIMAL(16, 5),
    sma_50 DECIMAL(16, 5),
    sma_200 DECIMAL(16, 5),
    ema_20 DECIMAL(16, 5),
    macd_value DECIMAL(12, 4),
    macd_signal DECIMAL(12, 4),
    macd_histogram DECIMAL(12, 4),
    bb_upper DECIMAL(16, 5),
    bb_middle DECIMAL(16, 5),
    bb_lower DECIMAL(16, 5),
    overall_signal VARCHAR(20),
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_date (summary_date),
    INDEX idx_date (summary_date DESC)
) ENGINE=InnoDB;

-- Populated by scripts/sync/scheduler/mt5_sync_service.py after each sync
-- cycle -- lets anything check MT5 sync freshness/error status without
-- needing to import the MetaTrader5 package itself (Airflow, which used to
-- be the motivating consumer here, has since been removed from this
-- project -- see docs/DECISIONS.md).
CREATE TABLE IF NOT EXISTS pipeline_status (
    pipeline_name    VARCHAR(64) PRIMARY KEY,
    last_success_at  DATETIME,
    last_row_count   INT,
    last_error       TEXT NULL
);

-- ── EURUSD Database ──────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS raw_eurusd
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_eurusd;

-- See the matching grant under `raw_gold` above for rationale.
GRANT ALL PRIVILEGES ON raw_eurusd.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

-- mt5_sync_service.py writes to whichever raw_* database its target
-- symbol maps to (see scripts/sync/scheduler/mt5_sync_service.py's RAW_DB),
-- so this database needs its own pipeline_status table too, not just
-- raw_gold's -- found missing when EURUSD's routing bug was fixed and the
-- service could finally reach this database for the first time.
CREATE TABLE IF NOT EXISTS pipeline_status (
    pipeline_name    VARCHAR(64) PRIMARY KEY,
    last_success_at  DATETIME,
    last_row_count   INT,
    last_error       TEXT NULL
);

CREATE TABLE IF NOT EXISTS m5 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo',
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS m15 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo',
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS h1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo',
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS h4 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS h6 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS d1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

-- Legacy processed-layer table, same status as raw_gold.signals above.
CREATE TABLE IF NOT EXISTS signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    signal_date DATE NOT NULL,
    signal_datetime DATETIME NOT NULL,
    signal_type VARCHAR(50) NOT NULL,
    signal_value DECIMAL(12, 4),
    signal_label VARCHAR(20) NOT NULL,
    description TEXT,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_signal (signal_datetime, signal_type),
    INDEX idx_date (signal_date DESC),
    INDEX idx_label (signal_label)
) ENGINE=InnoDB;

-- Legacy processed-layer table, same status as raw_gold.daily_summary above.
CREATE TABLE IF NOT EXISTS daily_summary (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    summary_date DATE NOT NULL,
    open_price DECIMAL(16, 5),
    close_price DECIMAL(16, 5),
    high_price DECIMAL(16, 5),
    low_price DECIMAL(16, 5),
    price_change DECIMAL(16, 5),
    price_change_pct DECIMAL(8, 4),
    volume BIGINT DEFAULT 0,
    rsi_14 DECIMAL(8, 4),
    sma_20 DECIMAL(16, 5),
    sma_50 DECIMAL(16, 5),
    sma_200 DECIMAL(16, 5),
    ema_20 DECIMAL(16, 5),
    macd_value DECIMAL(12, 4),
    macd_signal DECIMAL(12, 4),
    macd_histogram DECIMAL(12, 4),
    bb_upper DECIMAL(16, 5),
    bb_middle DECIMAL(16, 5),
    bb_lower DECIMAL(16, 5),
    overall_signal VARCHAR(20),
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_date (summary_date),
    INDEX idx_date (summary_date DESC)
) ENGINE=InnoDB;

-- ── DXY Database (US Dollar Index) ────────────────
-- h1 was Yahoo-sourced (DX-Y.NYB) until the Silver/DXY/VIX MT5-migration
-- decision -- now MT5-sourced (Eightcap symbol "USDX", confirmed live via
-- mt5.symbol_info()), same as gold/eurusd's h1. d1 is the deprecated
-- Yahoo table (left in place, no longer written to); the two divergence
-- models that use DXY as a driver (xau_dxy, eur_dxy) now resample d1 from
-- this h1 instead -- see docs/DECISIONS.md. No data_source column here
-- (predates that gold/eurusd-only convention).

CREATE DATABASE IF NOT EXISTS raw_dxy
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_dxy;

-- See the matching grant under `raw_gold` above for rationale.
GRANT ALL PRIVILEGES ON raw_dxy.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS h1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS d1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pipeline_status (
    pipeline_name    VARCHAR(64) PRIMARY KEY,
    last_success_at  DATETIME,
    last_row_count   INT,
    last_error       TEXT NULL
);

-- ── US10Y Database (US 10-Year Treasury Yield: ^TNX) ─────────
-- No MT5 equivalent exists (no bond/yield instrument on Eightcap,
-- confirmed via a live terminal check) -- stays Yahoo-sourced permanently.
-- uq_date (in addition to uq_dt) guards against the DST-mislabeling +
-- row-duplication bug found and cleaned up here: a pre-fix run wrote
-- price_datetime at naive local midnight (hour=0) for every date, and a
-- post-fix run (after fetcher/timezone_utils.py's to_utc_naive() was
-- added) wrote a second, correctly-converted row for the same dates --
-- neither collided against uq_dt alone since the hour differs, so both
-- survived. uq_date makes that impossible going forward: any second row
-- for an already-synced date now upserts in place instead of duplicating.
-- See docs/DECISIONS.md.

CREATE DATABASE IF NOT EXISTS raw_us10y
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_us10y;

-- See the matching grant under `raw_gold` above for rationale.
GRANT ALL PRIVILEGES ON raw_us10y.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS d1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    UNIQUE KEY uq_date (price_date),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

-- ── VIX Database (CBOE Volatility Index) ──────────────
-- d1 here is the deprecated Yahoo ^VIX table (left in place, no longer
-- written to). h1 is MT5-sourced (Eightcap symbol "VIX", confirmed live
-- via mt5.symbol_info()) as of the Silver/DXY/VIX MT5-migration decision
-- -- see docs/DECISIONS.md. No data_source column on h1 (matches
-- raw_dxy.h1's pre-existing shape, not raw_gold/raw_eurusd's).

CREATE DATABASE IF NOT EXISTS raw_vix
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_vix;

-- See the matching grant under `raw_gold` above for rationale.
GRANT ALL PRIVILEGES ON raw_vix.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS h1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS d1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pipeline_status (
    pipeline_name    VARCHAR(64) PRIMARY KEY,
    last_success_at  DATETIME,
    last_row_count   INT,
    last_error       TEXT NULL
);

-- ── GDX Database (VanEck Gold Miners ETF: GDX) ──────────────
-- No MT5 equivalent exists (no gold-miner ETF among Eightcap's US-listed
-- ETFs, confirmed via a live terminal check) -- stays Yahoo-sourced
-- permanently. uq_date guards against recurrence of the same
-- DST-mislabeling + row-duplication bug fixed here -- see the raw_us10y
-- comment above and docs/DECISIONS.md.

CREATE DATABASE IF NOT EXISTS raw_gdx
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_gdx;

-- See the matching grant under `raw_gold` above for rationale.
GRANT ALL PRIVILEGES ON raw_gdx.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS d1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    UNIQUE KEY uq_date (price_date),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

-- ── Silver ────────────────────────────────────────────────
-- Macro-driver scope only (like DXY/US10Y/VIX/GDX above), not a full
-- tradeable asset like XAUUSD/EURUSD -- no SMC/CRT/features/dashboard
-- chart support. d1 is the deprecated Yahoo SI=F table (left in place, no
-- longer written to; XAGUSD=X, the spot FX-style ticker, doesn't exist on
-- Yahoo -- 404/empty -- confirmed during the feasibility survey). h1 is
-- MT5-sourced (Eightcap symbol "XAGUSD", confirmed live via
-- mt5.symbol_info()) as of the Silver/DXY/VIX MT5-migration decision --
-- the xau_xag divergence model now resamples d1 from this h1 instead, see
-- docs/DECISIONS.md. No data_source column on h1 (matches raw_dxy.h1's
-- pre-existing shape, not raw_gold/raw_eurusd's).

CREATE DATABASE IF NOT EXISTS raw_silver
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_silver;

GRANT ALL PRIVILEGES ON raw_silver.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS h1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS d1 (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    price_date DATE NOT NULL,
    price_datetime DATETIME NOT NULL,
    open_price DECIMAL(16, 5) NOT NULL,
    high_price DECIMAL(16, 5) NOT NULL,
    low_price DECIMAL(16, 5) NOT NULL,
    close_price DECIMAL(16, 5) NOT NULL,
    volume BIGINT DEFAULT 0,
    inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_dt (price_datetime),
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pipeline_status (
    pipeline_name    VARCHAR(64) PRIMARY KEY,
    last_success_at  DATETIME,
    last_row_count   INT,
    last_error       TEXT NULL
);

-- ── COT Database (CFTC Commitment of Traders, Legacy report) ────
-- Weekly, not daily/hourly like every other raw table — deliberately a
-- different shape (report_date instead of price_datetime, no OHLC) since
-- forcing weekly positioning data into an OHLCV-shaped table would be
-- misleading. One table per market (gold, eur) since the Legacy report's
-- Commercial/Non-Commercial category schema is uniform across markets —
-- see fetcher/cot_fetcher.py for why Legacy was chosen over
-- Disaggregated/TFF (which use different, market-type-specific category
-- schemas that don't unify into one table shape).

CREATE DATABASE IF NOT EXISTS raw_cot
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_cot;

GRANT ALL PRIVILEGES ON raw_cot.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS gold (
    id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date              DATE NOT NULL,
    open_interest_all        BIGINT,
    noncommercial_long       BIGINT,
    noncommercial_short      BIGINT,
    noncommercial_spreading  BIGINT,
    commercial_long          BIGINT,
    commercial_short         BIGINT,
    nonreportable_long       BIGINT,
    nonreportable_short      BIGINT,
    -- Computed at fetch time for convenience (self-contained row, same
    -- convention as e.g. crt_signals' repeated session summary columns).
    commercial_net_position     BIGINT,
    noncommercial_net_position  BIGINT,
    inserted_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS eur (
    id                       BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date              DATE NOT NULL,
    open_interest_all        BIGINT,
    noncommercial_long       BIGINT,
    noncommercial_short      BIGINT,
    noncommercial_spreading  BIGINT,
    commercial_long          BIGINT,
    commercial_short         BIGINT,
    nonreportable_long       BIGINT,
    nonreportable_short      BIGINT,
    commercial_net_position     BIGINT,
    noncommercial_net_position  BIGINT,
    inserted_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;

-- ── SPDR Database (SPDR Gold Shares / GLD daily holdings) ────────
-- Daily (unlike COT), but not OHLCV either — GLD's own share price is a
-- secondary detail here; the reason this table exists is
-- total_ounces_in_trust/tonnes_of_gold (physical gold backing the ETF),
-- which is what XAU vs SPDR divergence actually compares against gold's
-- own price. Full source row persisted at the raw layer (see
-- fetcher/spdr_fetcher.py) even though divergence detection will only
-- use the holdings columns — narrowing to just those would lose fidelity
-- for no benefit, and the raw layer's job is to mirror the source.

CREATE DATABASE IF NOT EXISTS raw_spdr
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_spdr;

GRANT ALL PRIVILEGES ON raw_spdr.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS gld (
    id                        BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date               DATE NOT NULL,
    closing_price             DECIMAL(16,5) NULL,
    ounces_per_share          DECIMAL(12,8) NULL,
    nav_per_share_1030        DECIMAL(16,6) NULL,
    indicative_price_415      DECIMAL(16,5) NULL,
    bid_ask_midpoint_415      DECIMAL(16,5) NULL,
    premium_discount_pct      DECIMAL(10,6) NULL,
    daily_share_volume        BIGINT NULL,
    total_ounces_in_trust     DECIMAL(20,4) NULL,
    tonnes_of_gold            DECIMAL(16,4) NULL,
    total_nav                 DECIMAL(24,4) NULL,
    inserted_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;

-- ── GPR Database (Geopolitical Risk Index, Caldara & Iacoviello / Fed) ───
-- Daily, single global index (not per-market like COT) -- gprd is the
-- headline index, gprd_act/gprd_threat are its two sub-components (actual
-- events vs. threats), gprd_ma7/gprd_ma30 are the source's own precomputed
-- smoothed series, persisted as-is rather than recomputed here so this
-- table always matches matteoiacoviello.com's own published numbers
-- exactly. See fetcher/gpr_fetcher.py for the source file's other columns
-- (N10D, event, var_name, var_label) that aren't persisted -- they're
-- either redundant with gprd or only populated for older/one-off entries,
-- not part of the daily numeric series this project consumes.

CREATE DATABASE IF NOT EXISTS raw_gpr
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_gpr;

GRANT ALL PRIVILEGES ON raw_gpr.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS gpr (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date       DATE NOT NULL,
    gprd              DECIMAL(12,6) NULL,
    gprd_act          DECIMAL(12,6) NULL,
    gprd_threat       DECIMAL(12,6) NULL,
    gprd_ma7          DECIMAL(12,6) NULL,
    gprd_ma30         DECIMAL(12,6) NULL,
    inserted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;

-- ── FRED Database (Federal Reserve Economic Data) ────────────────
-- One database, one table per series (same precedent as raw_cot's
-- gold/eur tables under one database) since every FRED series shares the
-- same fetch mechanism (fred.stlouisfed.org's public CSV endpoint, no API
-- key/fredapi dependency needed) and the same (report_date, value) shape.
-- fed_funds = DFF (true daily Federal Funds Rate -- NOT FEDFUNDS, which is
-- a monthly average and would silently misrepresent "daily" granularity).
-- tips10y = DFII10 (10-Year Treasury Inflation-Indexed real yield), the
-- single most commonly cited macro driver of gold in the literature.
-- Both series are already daily-native (no resampling needed, unlike CPI
-- which is monthly and forward-filled via merge_asof same as COT).

CREATE DATABASE IF NOT EXISTS raw_fred
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_fred;

GRANT ALL PRIVILEGES ON raw_fred.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS fed_funds (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date       DATE NOT NULL,
    rate_pct          DECIMAL(8,4) NOT NULL,
    inserted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS tips10y (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date       DATE NOT NULL,
    real_yield_pct    DECIMAL(8,4) NOT NULL,
    inserted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;

-- CPIAUCSL is monthly (report_date always the 1st of the month) -- the
-- granularity mismatch against daily gold is handled downstream via
-- merge_asof(direction="backward"), same forward-fill pattern as COT's
-- weekly reports onto daily price, not by anything in this table's shape.
CREATE TABLE IF NOT EXISTS cpi (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date       DATE NOT NULL,
    cpi_index         DECIMAL(10,3) NOT NULL,
    inserted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;

-- ── ECB Database (euro area 10Y AAA yield curve spot rate) ───────
-- The long-deferred EUR yield-spread divergence source -- daily series
-- (YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y), NOT the monthly "convergence
-- purposes" series ECB also publishes, which would mismatch US10Y's
-- daily granularity. See fetcher/ecb_fetcher.py for the full series key
-- and why this one (not the monthly alternative) was chosen.

CREATE DATABASE IF NOT EXISTS raw_ecb
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_ecb;

GRANT ALL PRIVILEGES ON raw_ecb.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

CREATE TABLE IF NOT EXISTS eu10y (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    report_date       DATE NOT NULL,
    yield_pct         DECIMAL(10,6) NOT NULL,
    inserted_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_report_date (report_date),
    INDEX idx_date (report_date DESC)
) ENGINE=InnoDB;
