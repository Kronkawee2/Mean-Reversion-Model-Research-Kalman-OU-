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
-- ── Airflow Database ─────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS airflow_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

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

-- Lets a future Airflow SqlSensor check MT5 sync freshness without
-- Airflow ever importing the MetaTrader5 package directly.
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

CREATE TABLE IF NOT EXISTS m5 (
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

CREATE TABLE IF NOT EXISTS m15 (
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

-- ── DXY Database (US Dollar Index: DX-Y.NYB) ────────────────

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

-- ── US10Y Database (US 10-Year Treasury Yield: ^TNX) ─────────

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
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

-- ── VIX Database (CBOE Volatility Index: ^VIX) ──────────────

CREATE DATABASE IF NOT EXISTS raw_vix
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE raw_vix;

-- See the matching grant under `raw_gold` above for rationale.
GRANT ALL PRIVILEGES ON raw_vix.* TO 'quant_user'@'%';
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
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

-- ── GDX Database (VanEck Gold Miners ETF: GDX) ──────────────

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
    INDEX idx_date (price_date DESC)
) ENGINE=InnoDB;

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
