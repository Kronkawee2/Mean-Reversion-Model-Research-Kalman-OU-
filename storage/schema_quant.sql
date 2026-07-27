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

