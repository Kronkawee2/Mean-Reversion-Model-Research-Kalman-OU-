-- ============================================================
-- Step 3 (Mart) — Trade signals & backtest schema.
-- Split out of schema_raw.sql (formerly schema_quant.sql): this content
-- is derived/decision-layer output (trade signals, backtest results), not
-- raw market data, so it doesn't belong in the raw-data schema file even
-- though it predates this project's raw/curated/mart layer naming.
-- ============================================================

-- ── Signals Database (Step 3 — Trade Signals & Backtest) ─────

CREATE DATABASE IF NOT EXISTS `mart`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `mart`;

-- See the matching grant under `raw_gold` in schema_raw.sql for rationale. The
-- original schema_quant.sql never had this grant for the signals database
-- (a pre-existing gap, not introduced by this split); added here so a
-- fresh docker-compose up doesn't need a manual GRANT step either.
GRANT ALL PRIVILEGES ON `mart`.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

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
