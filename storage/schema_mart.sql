-- ============================================================
-- Step 3 (Mart) — currently empty.
-- Split out of schema_raw.sql (formerly schema_quant.sql): this database
-- is for derived/decision-layer output, not raw market data, so it
-- doesn't belong in the raw-data schema file even though it predates
-- this project's raw/curated/mart layer naming.
--
-- Dashboard rebuild note (2026-08): this file used to define
-- `trade_signals`, `backtest_runs`, and `equity_curve` -- all output of
-- the OLD, pre-curated-schema ad-hoc backtester/signal scorer
-- (analysis/backtester/backtest.py, MTFStrategyEngine-signal based, and
-- the old dashboard/app.py's live 7-point confluence scorer). All three
-- were confirmed empty of real data (`backtest_runs`/`equity_curve` had
-- zero rows ever written by any code path; `trade_signals`'s only 17 rows
-- were artifacts of this session's own dashboard smoke-testing, all
-- sharing one inserted_at timestamp) and dropped once
-- dashboard/pages/3_LTF_Triggers.py (the last remaining reader/writer,
-- formerly 1_signal.py) was rebuilt against
-- curated_<symbol>.ltf_trigger_signals -- `backtest_runs` in particular
-- collided in name with the REAL, populated `curated_gold.backtest_runs`
-- (analysis/backtester/structural_backtest_engine.py), which was a
-- genuine footgun for anyone reading the schema.
--
-- The `mart` database itself is kept (empty) since it's still this
-- project's conceptual home for cross-symbol/aggregate dashboard output,
-- should something real need to live there later.
-- ============================================================

CREATE DATABASE IF NOT EXISTS `mart`
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `mart`;

-- See the matching grant under `raw_gold` in schema_raw.sql for rationale. The
-- original schema_quant.sql never had this grant for the signals database
-- (a pre-existing gap, not introduced by this split); added here so a
-- fresh docker-compose up doesn't need a manual GRANT step either.
GRANT ALL PRIVILEGES ON `mart`.* TO 'quant_user'@'%';
FLUSH PRIVILEGES;
