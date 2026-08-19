# MT5 Data Fetcher (Phase 0)

Read-only market data access to Eightcap via the official `MetaTrader5` Python
package. Windows-only, native IPC to the local terminal — no Docker, no
MySQL, no Airflow, no order placement. Scope ends at returning pandas
DataFrames; nothing here writes to a database.

## Requirements

- Windows 64-bit
- Eightcap MT5 terminal installed and (recommended) logged in
- Python 3.13, 64-bit

```
pip install -r requirements-mt5.txt
```

## Setup

```
copy .env.mt5.example .env
```

Fill in `MT5_PATH`, and optionally `MT5_LOGIN` / `MT5_PASSWORD` / `MT5_SERVER`
if the terminal isn't already logged in. If the terminal is already logged
in, `connect()` works with just `mt5.initialize()` — login fields can stay
blank.

## Test the connection

```
python tests/test_mt5_connection.py
```

This connects, prints account info, tries the known Eightcap gold symbol
variants (`XAUUSD`, `XAUUSD.a`, `XAUUSDm`, `GOLD`) until one verifies, prints
the latest tick, and fetches the last 5 closed M5 candles.

## CLI usage

```
python scripts/sync/mt5_data_fetcher.py --symbol XAUUSD --timeframe M5 --count 20
python scripts/sync/mt5_data_fetcher.py --symbol XAUUSD --timeframe M5 \
  --start 2026-08-01T00:00:00Z --end 2026-08-02T00:00:00Z --output test_output.csv
```

Flags: `--symbol --timeframe --start --end --count --output --include-incomplete --debug`

- Without `--start`/`--end`, fetches the latest `--count` closed candles.
- With both, fetches the historical range (chunking is available
  programmatically via `get_rates(..., chunk_days=N)`, not yet a CLI flag).
- `--include-incomplete` keeps the currently-forming candle instead of
  dropping it.

## Timezone assumption

MT5 reports candle/tick times as the broker's server clock. This module
assumes Eightcap's server time is UTC-aligned and treats the raw epoch
timestamp as UTC when building `time_utc`. If a manual cross-check (§10 of
the engineering brief) shows an offset against the MT5 terminal's own chart,
that offset needs to be measured and applied — this module does not attempt
to auto-detect broker UTC offset.

**Validated 2026-08-10** against account 5124984 / server `EightcapGlobal-Live`:
offset measured at 0 hours (fetcher's `time_utc` for the last closed M5
candle matched the terminal chart's displayed time exactly; XAUUSD price
level sanity-checked against the live market). Symbol resolved on the first
try as `XAUUSD` — no suffix fallback needed. Re-verify this if the account,
server, or broker changes, or twice a year around EU/US DST transitions,
by rerunning `tests/test_mt5_connection.py` and comparing its printed candle
times against the terminal's own chart.

## Sync service (Phase 0.5)

`scripts/sync/scheduler/mt5_sync_service.py` polls closed M5/M15/H1 candles for XAUUSD
and upserts them into the `raw_gold` MySQL database (`localhost:3308`) with
`data_source='mt5'`. EURUSD is out of scope until this is validated
end-to-end. It reuses `MT5DataFetcher.get_rates_incremental()` to catch up
from the last stored `price_datetime` (bootstrapping the last 500 bars if a
table is empty), retries MT5 connect and MySQL connect with exponential
backoff, and records each cycle's outcome in the `pipeline_status` table so
anything else can check freshness without importing `MetaTrader5` itself
(Airflow, the original motivating consumer here, has since been removed
from this project -- see docs/DECISIONS.md).

Apply the schema migration first (`storage/migrations/001_mt5_integration.sql`,
adds `data_source` to `raw_gold.m5/m15/h1` and creates `pipeline_status` — not
auto-applied since the `raw_gold` volume already has data):

```
docker exec -i gold_mysql_active mysql -uroot -p raw_gold < storage/migrations/001_mt5_integration.sql
```

Run:

```
python scripts/sync/scheduler/mt5_sync_service.py --once      # one cycle, e.g. for Windows Task Scheduler
python scripts/sync/scheduler/mt5_sync_service.py --interval 60   # long-lived loop
```

DB credentials are read from `.env` (`DB_HOST`, `DB_PORT`, `DB_USER`,
`DB_PASSWORD`); `DB_PORT` defaults to `3308` to match the host-side Docker
port mapping. `schema_raw.sql` now grants `quant_user` privileges on
`raw_gold` directly (hardcoded to that username — update the `GRANT` line in
`schema_raw.sql` if `DB_USER` in `.env` ever changes), so a fresh
`docker-compose up` needs no manual grant step. (An earlier, dead
`sync_step1.py` script that connected with different, hardcoded credentials
and a wrong DB port has since been removed — its scope was fully redundant
with `quant_backend.py` + MT5 ingestion.)

## API surface

`MT5DataFetcher`: `connect`, `disconnect`, `is_connected`, `get_account_info`,
`check_symbol`, `search_gold_symbols`, `get_available_symbols`,
`get_latest_tick`, `get_rates`, `get_latest_rates`, `get_rates_incremental`,
`get_multiple_timeframes`, `get_ticks`.

Exceptions: `MT5ConnectionError`, `MT5LoginError`, `MT5SymbolError`,
`MT5DataError`, `MT5TimeframeError`.

Supported timeframes: `M5`, `M15`, `H1` (mapped explicitly to
`mt5.TIMEFRAME_*` constants — raw strings are never passed to the API).
