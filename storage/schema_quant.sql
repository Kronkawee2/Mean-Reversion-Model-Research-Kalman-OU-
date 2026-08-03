-- ============================================================
-- Quant Trader Schema
-- Grouped by symbol: each symbol = 1 database
-- ============================================================

-- ── GOLD Database ────────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS gold
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE gold;

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

-- ── EURUSD Database ──────────────────────────────────────────

CREATE DATABASE IF NOT EXISTS eurusd
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE eurusd;

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

CREATE DATABASE IF NOT EXISTS dxy
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE dxy;

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

CREATE DATABASE IF NOT EXISTS us10y
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE us10y;

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

CREATE DATABASE IF NOT EXISTS vix
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE vix;

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

CREATE DATABASE IF NOT EXISTS gdx
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE gdx;

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

-- ── Signals Database (Step 3 — Trade Signals & Backtest) ─────

CREATE DATABASE IF NOT EXISTS `signals`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `signals`;

CREATE TABLE IF NOT EXISTS `trade_signals` (
    id                 BIGINT        AUTO_INCREMENT PRIMARY KEY,
    signal_uuid        CHAR(8)       NOT NULL,
    symbol             VARCHAR(20)   NOT NULL,
    tf_exec            VARCHAR(10)   NOT NULL,
    tf_htf             VARCHAR(10)   NOT NULL DEFAULT '1h',
    formed_at          DATETIME      NOT NULL,
    direction          ENUM('bullish','bearish') NOT NULL,
    entry              DECIMAL(16,5) NOT NULL,
    stop_loss          DECIMAL(16,5) NOT NULL,
    take_profit        DECIMAL(16,5) NOT NULL,
    atr_14             DECIMAL(16,5) NOT NULL,
    risk_reward        DECIMAL(5,2)  NOT NULL DEFAULT 2.00,
    confluence_score   TINYINT       NOT NULL,
    confluence_max     TINYINT       NOT NULL DEFAULT 7,
    conditions         VARCHAR(500)  NOT NULL DEFAULT '',
    htf_bias           VARCHAR(20)   NOT NULL DEFAULT 'NEUTRAL',
    confidence         DECIMAL(5,4)  NOT NULL DEFAULT 0,
    status             ENUM('PENDING','WIN','LOSS','CANCELLED') NOT NULL DEFAULT 'PENDING',
    pnl_pts            DECIMAL(16,5) DEFAULT NULL,
    bars_held          SMALLINT      DEFAULT NULL,
    closed_at          DATETIME      DEFAULT NULL,
    inserted_at        TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_signal (symbol, tf_exec, formed_at, direction),
    INDEX idx_symbol    (symbol),
    INDEX idx_status    (status),
    INDEX idx_formed    (formed_at),
    INDEX idx_symbol_tf (symbol, tf_exec)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `backtest_runs` (
    id                 BIGINT        AUTO_INCREMENT PRIMARY KEY,
    run_uuid           CHAR(8)       NOT NULL,
    symbol             VARCHAR(20)   NOT NULL,
    tf_exec            VARCHAR(10)   NOT NULL,
    tf_htf             VARCHAR(10)   NOT NULL DEFAULT '1h',
    min_confluence     TINYINT       NOT NULL DEFAULT 4,
    atr_sl_mult        DECIMAL(4,2)  NOT NULL DEFAULT 1.50,
    risk_reward        DECIMAL(4,2)  NOT NULL DEFAULT 2.00,
    period_start       DATETIME      NOT NULL,
    period_end         DATETIME      NOT NULL,
    total_signals      INT           NOT NULL DEFAULT 0,
    wins               INT           NOT NULL DEFAULT 0,
    losses             INT           NOT NULL DEFAULT 0,
    pending            INT           NOT NULL DEFAULT 0,
    win_rate           DECIMAL(6,4)  NOT NULL DEFAULT 0,
    gross_profit       DECIMAL(16,5) NOT NULL DEFAULT 0,
    gross_loss         DECIMAL(16,5) NOT NULL DEFAULT 0,
    profit_factor      DECIMAL(10,4) NOT NULL DEFAULT 0,
    net_pnl            DECIMAL(16,5) NOT NULL DEFAULT 0,
    avg_win            DECIMAL(16,5) NOT NULL DEFAULT 0,
    avg_loss           DECIMAL(16,5) NOT NULL DEFAULT 0,
    avg_rr_actual      DECIMAL(6,3)  NOT NULL DEFAULT 0,
    max_drawdown       DECIMAL(16,5) NOT NULL DEFAULT 0,
    max_drawdown_pct   DECIMAL(6,4)  NOT NULL DEFAULT 0,
    sharpe_ratio       DECIMAL(10,4) NOT NULL DEFAULT 0,
    run_at             TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_run_symbol (symbol, tf_exec),
    INDEX idx_run_at     (run_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS `equity_curve` (
    id             BIGINT        AUTO_INCREMENT PRIMARY KEY,
    run_uuid       CHAR(8)       NOT NULL,
    symbol         VARCHAR(20)   NOT NULL,
    tf_exec        VARCHAR(10)   NOT NULL,
    snap_date      DATETIME      NOT NULL,
    cumulative_pnl DECIMAL(16,5) NOT NULL,
    trade_count    INT           NOT NULL DEFAULT 0,
    INDEX idx_eq_run    (run_uuid),
    INDEX idx_eq_symbol (symbol, tf_exec, snap_date)
) ENGINE=InnoDB;
