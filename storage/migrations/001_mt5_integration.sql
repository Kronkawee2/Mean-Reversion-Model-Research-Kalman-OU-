-- ============================================================
-- Migration 001: MT5 integration (Phase 0.5 / Phase 0)
-- Scope: `raw_gold` database only. EURUSD is out of scope until the
-- MT5 sync service is validated end-to-end for XAUUSD.
--
-- Run manually against the running MySQL container, e.g.:
--   docker exec -i gold_mysql_active mysql -uroot -p raw_gold < storage/migrations/001_mt5_integration.sql
-- This file is NOT wired into docker-entrypoint-initdb.d — it only
-- runs on fresh volume init via schema_raw.sql, and raw_gold already
-- has data, so this migration must be applied explicitly instead.
-- Already applied against the pre-rename `gold` database (data_source
-- columns exist); this file's ALTER TABLE statements have no IF NOT
-- EXISTS guard and would error if re-run post-rename, since the columns
-- already carried over with the renamed database. Kept for reference /
-- fresh-volume documentation only, not meant to be re-run.
-- ============================================================

USE raw_gold;

-- Same grant now baked into schema_raw.sql for fresh volumes; repeated
-- here so applying this migration to an existing container also fixes
-- privileges without a separate manual GRANT step.
GRANT ALL PRIVILEGES ON raw_gold.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;

-- Track provenance so pre-existing Yahoo-sourced rows are distinguishable
-- from new MT5-sourced rows during the transition period.
ALTER TABLE m5  ADD COLUMN data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo' AFTER volume;
ALTER TABLE m15 ADD COLUMN data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo' AFTER volume;
ALTER TABLE h1  ADD COLUMN data_source ENUM('yahoo','mt5') NOT NULL DEFAULT 'yahoo' AFTER volume;

-- Note on the "(symbol, timeframe, time_utc) unique index" requirement from
-- the brief: this schema already models symbol as database (raw_gold/raw_eurusd)
-- and timeframe as table (m5/m15/h1/...), each with
-- `UNIQUE KEY uq_dt (price_datetime)`. That constraint already makes
-- upserts safe from either source (see mt5_sync_service.py's
-- ON DUPLICATE KEY UPDATE), so no redundant composite column/index is
-- added here.

-- Lets a future Airflow SqlSensor check MT5 sync freshness without
-- Airflow ever importing the MetaTrader5 package directly.
CREATE TABLE IF NOT EXISTS pipeline_status (
    pipeline_name    VARCHAR(64) PRIMARY KEY,
    last_success_at  DATETIME,
    last_row_count   INT,
    last_error       TEXT NULL
);
