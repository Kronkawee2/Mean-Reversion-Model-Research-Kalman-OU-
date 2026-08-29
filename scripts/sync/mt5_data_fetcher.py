"""
MT5DataFetcher: read-only market data access layer for MetaTrader5 (Eightcap).

Windows-only. No MySQL, no Docker, no Airflow, no order placement.
Assumes the MT5 terminal's server time is UTC-aligned; all returned
`time_utc` columns are built on that assumption (see README-MT5.md).
"""

import argparse
import logging
import os
import sys
import time as time_module
from datetime import datetime, timezone

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logger = logging.getLogger("mt5_data_fetcher")


class MT5ConnectionError(Exception):
    pass


class MT5LoginError(Exception):
    pass


class MT5SymbolError(Exception):
    pass


class MT5DataError(Exception):
    pass


class MT5TimeframeError(Exception):
    pass


TIMEFRAME_MAP = {
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
}

# seconds per closed-candle duration, used to decide if the latest bar is closed
TIMEFRAME_SECONDS = {
    "M5": 300,
    "M15": 900,
    "H1": 3600,
}

RATES_COLUMNS = ["time", "time_utc", "open", "high", "low", "close",
                  "tick_volume", "spread", "real_volume"]
TICK_COLUMNS = ["time", "time_utc", "bid", "ask", "last", "volume", "flags"]


def _require_mt5():
    if mt5 is None:
        raise MT5ConnectionError(
            "MetaTrader5 package is not installed. Run: pip install -r requirements-mt5.txt"
        )


def _resolve_timeframe(timeframe: str):
    _require_mt5()
    if timeframe not in TIMEFRAME_MAP:
        raise MT5TimeframeError(
            f"Unrecognized timeframe {timeframe!r}. Supported: {sorted(TIMEFRAME_MAP)}"
        )
    return getattr(mt5, TIMEFRAME_MAP[timeframe])


def _parse_time(value) -> pd.Timestamp:
    """Accept tz-aware datetime or ISO string; reject naive input. Returns UTC pd.Timestamp."""
    if isinstance(value, str):
        ts = pd.Timestamp(value)
    elif isinstance(value, datetime):
        ts = pd.Timestamp(value)
    elif isinstance(value, pd.Timestamp):
        ts = value
    else:
        raise MT5DataError(f"Unsupported time value type: {type(value)!r}")

    if ts.tzinfo is None:
        raise MT5DataError(
            f"Naive datetime {value!r} is not allowed — pass a timezone-aware "
            f"datetime or an ISO string with an explicit offset (e.g. 'Z')."
        )
    return ts.tz_convert("UTC")


def _to_naive_utc(ts: pd.Timestamp) -> datetime:
    """
    Returns a naive datetime for mt5.copy_rates_range()'s date_from/date_to.

    NOT actually "naive UTC" despite the name staying for now for minimal
    diff -- mt5.copy_rates_range() silently reinterprets a naive
    datetime.datetime using the LOCAL SYSTEM TIMEZONE (not UTC), a
    documented quirk of the MetaTrader5 Python API. Converting to true-UTC
    wall-clock numbers and stripping tzinfo (the old behavior) therefore
    got fed back through MT5's local-timezone reinterpretation and silently
    queried the wrong window -- confirmed empirically on this machine
    (UTC+7): passing labeled UTC bounds [X, Y] returned bars labeled
    [X-7h, Y-7h] instead. Converting to LOCAL wall-clock time first means
    MT5's own local->UTC reinterpretation lands back on the UTC instant
    actually intended, verified against a known-correct ground truth
    (get_latest_rates, a position-based call unaffected by this bug).
    """
    return ts.tz_convert("UTC").to_pydatetime().astimezone().replace(tzinfo=None)


def _empty_rates_df() -> pd.DataFrame:
    df = pd.DataFrame(columns=RATES_COLUMNS)
    df["time"] = pd.to_datetime(df["time"])
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    for col in ["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]:
        df[col] = pd.to_numeric(df[col])
    return df


def _empty_ticks_df() -> pd.DataFrame:
    df = pd.DataFrame(columns=TICK_COLUMNS)
    df["time"] = pd.to_datetime(df["time"])
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    for col in ["bid", "ask", "last", "volume", "flags"]:
        df[col] = pd.to_numeric(df[col])
    return df


def _rates_array_to_df(rates) -> pd.DataFrame:
    if rates is None or len(rates) == 0:
        return _empty_rates_df()
    df = pd.DataFrame(rates)
    df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[RATES_COLUMNS]
    df = df.drop_duplicates(subset="time_utc").sort_values("time_utc").reset_index(drop=True)
    return df


def _ticks_array_to_df(ticks) -> pd.DataFrame:
    if ticks is None or len(ticks) == 0:
        return _empty_ticks_df()
    df = pd.DataFrame(ticks)
    df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[TICK_COLUMNS]
    df = df.drop_duplicates(subset="time_utc").sort_values("time_utc").reset_index(drop=True)
    return df


class MT5DataFetcher:
    def __init__(self, mt5_path=None, login=None, password=None, server=None):
        self.mt5_path = mt5_path or os.environ.get("MT5_PATH") or None
        self.login = login or os.environ.get("MT5_LOGIN") or None
        self.password = password or os.environ.get("MT5_PASSWORD") or None
        self.server = server or os.environ.get("MT5_SERVER") or None
        self._connected = False
        # Broker platform time vs true UTC, measured fresh at check_symbol()
        # time (not hardcoded: confirmed via real-data cross-check that this
        # broker reports EEST/EET-style platform time, currently +3h ahead
        # of true UTC, which shifts to +2h when EU DST ends -- any fixed
        # constant would silently go wrong at the next DST boundary).
        self.broker_utc_offset = None

    def connect(self):
        _require_mt5()
        logger.info(
            "Connecting to MT5 (path=%s, server=%s, login=%s)",
            self.mt5_path, self.server, self.login if not self.login else "***",
        )
        init_kwargs = {}
        if self.mt5_path:
            init_kwargs["path"] = self.mt5_path

        if not mt5.initialize(**init_kwargs):
            code, desc = mt5.last_error()
            raise MT5ConnectionError(f"mt5.initialize() failed: [{code}] {desc}")

        if self.login and self.password and self.server:
            if not mt5.login(int(self.login), password=self.password, server=self.server):
                code, desc = mt5.last_error()
                mt5.shutdown()
                raise MT5LoginError(f"mt5.login() failed: [{code}] {desc}")

        account_info = mt5.account_info()
        if account_info is None:
            code, desc = mt5.last_error()
            mt5.shutdown()
            raise MT5ConnectionError(f"account_info() unavailable after connect: [{code}] {desc}")

        self._connected = True
        logger.info("Connected. Account login=%s server=%s", account_info.login, account_info.server)
        return account_info

    def disconnect(self):
        if mt5 is not None:
            mt5.shutdown()
        self._connected = False
        logger.info("Disconnected from MT5")

    def is_connected(self) -> bool:
        if not self._connected or mt5 is None:
            return False
        return mt5.terminal_info() is not None

    def get_account_info(self) -> dict:
        info = mt5.account_info()
        if info is None:
            code, desc = mt5.last_error()
            raise MT5ConnectionError(f"account_info() failed: [{code}] {desc}")
        return info._asdict()

    def check_symbol(self, symbol: str) -> dict:
        info = mt5.symbol_info(symbol)
        if info is None:
            near = self.search_gold_symbols()
            raise MT5SymbolError(
                f"Symbol {symbol!r} not found. Near matches: {near or 'none found'}"
            )
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                code, desc = mt5.last_error()
                raise MT5SymbolError(f"Could not select {symbol!r} in Market Watch: [{code}] {desc}")
            info = mt5.symbol_info(symbol)
        logger.info("Symbol %s verified (visible=%s)", symbol, info.visible)
        self._calibrate_broker_utc_offset(symbol)
        return info._asdict()

    def _calibrate_broker_utc_offset(self, symbol: str) -> None:
        """
        Measures how far the broker's own clock (as embedded in the raw
        epoch timestamps MT5 reports for ticks/rates) is from true UTC,
        using a live tick for `symbol` against this system's own UTC clock
        at the same instant. Re-measured every call (check_symbol() is
        called at the start of every sync cycle) so it self-corrects
        across DST transitions without any manual recalibration.
        """
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            code, desc = mt5.last_error()
            raise MT5DataError(f"symbol_info_tick({symbol!r}) failed during UTC offset calibration: [{code}] {desc}")
        broker_time = pd.Timestamp(tick.time, unit="s", tz="UTC")
        true_utc_now = pd.Timestamp.now(tz="UTC")
        # Rounded to the nearest minute -- real broker-vs-UTC offsets are
        # always whole-hour/half-hour amounts (DST shifts included), so any
        # sub-minute component here is pure measurement noise from reading
        # two live clocks (tick.time vs this system's clock) at slightly
        # different instants. Left unrounded, that noise (a few seconds,
        # different every call since check_symbol() recalibrates on every
        # sync cycle) got subtracted into every bar's stored price_datetime
        # -- shifting the SAME real M5/M15/H1 bar by a couple seconds on
        # each run, which missed the `uq_dt` unique-key match on upsert and
        # inserted a near-duplicate row instead of updating the existing
        # one (confirmed: 16-19 duplicate-bar clusters per symbol/timeframe
        # across raw history, all landing exactly on dates this pipeline
        # was run more than once). Rounding removes the noise while keeping
        # the self-correcting-across-DST behavior the un-rounded version
        # was already relying on.
        raw_offset = broker_time - true_utc_now
        self.broker_utc_offset = raw_offset.round("min")
        logger.info("Calibrated broker UTC offset: %s (raw=%s, broker=%s, true_utc=%s)",
                    self.broker_utc_offset, raw_offset, broker_time, true_utc_now)

    def _require_calibration(self) -> pd.Timedelta:
        if self.broker_utc_offset is None:
            raise MT5DataError(
                "broker_utc_offset not calibrated -- call check_symbol(symbol) "
                "before fetching rates/ticks (it measures the current broker-vs-UTC "
                "offset, which is not a fixed constant since it shifts with DST)."
            )
        return self.broker_utc_offset

    def _correct_to_true_utc(self, df: pd.DataFrame) -> pd.DataFrame:
        """Subtracts the calibrated broker-vs-UTC offset from time_utc/time so returned timestamps are true UTC, not broker platform time."""
        if df.empty:
            return df
        offset = self._require_calibration()
        df = df.copy()
        df["time_utc"] = df["time_utc"] - offset
        df["time"] = df["time"] - offset
        return df

    def search_gold_symbols(self) -> list:
        symbols = mt5.symbols_get() or []
        return [s.name for s in symbols if "XAU" in s.name.upper() or "GOLD" in s.name.upper()]

    def get_available_symbols(self) -> list:
        symbols = mt5.symbols_get() or []
        return [s.name for s in symbols]

    def get_latest_tick(self, symbol: str) -> dict:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            code, desc = mt5.last_error()
            raise MT5DataError(f"symbol_info_tick({symbol!r}) failed: [{code}] {desc}")
        return tick._asdict()

    def get_rates(self, symbol: str, timeframe: str, start, end, chunk_days=None) -> pd.DataFrame:
        tf = _resolve_timeframe(timeframe)
        start_utc = _parse_time(start)
        end_utc = _parse_time(end)
        # copy_rates_range's date_from/date_to are compared against the
        # broker's own server-clock bar index, not true UTC -- shift the
        # true-UTC bounds forward by the calibrated broker offset BEFORE
        # the local-system-timezone compensation (_to_naive_utc), or the
        # query silently lands on the wrong window (confirmed empirically:
        # without this, a query for true-UTC "last 1h" returned bars from
        # ~3h earlier, exactly matching the broker's own +3h offset).
        broker_offset = self._require_calibration()

        ranges = [(start_utc, end_utc)]
        if chunk_days:
            ranges = []
            cursor = start_utc
            step = pd.Timedelta(days=chunk_days)
            while cursor < end_utc:
                chunk_end = min(cursor + step, end_utc)
                ranges.append((cursor, chunk_end))
                cursor = chunk_end

        frames = []
        for i, (chunk_start, chunk_end) in enumerate(ranges, start=1):
            t0 = time_module.monotonic()
            try:
                rates = mt5.copy_rates_range(
                    symbol, tf,
                    _to_naive_utc(chunk_start + broker_offset),
                    _to_naive_utc(chunk_end + broker_offset),
                )
            except Exception as e:
                raise MT5DataError(
                    f"get_rates chunk {i}/{len(ranges)} [{chunk_start} -> {chunk_end}] "
                    f"raised: {e}"
                )
            if rates is None:
                code, desc = mt5.last_error()
                raise MT5DataError(
                    f"get_rates chunk {i}/{len(ranges)} [{chunk_start} -> {chunk_end}] "
                    f"failed: [{code}] {desc}"
                )
            elapsed = time_module.monotonic() - t0
            logger.info(
                "Fetched chunk %d/%d [%s -> %s]: %d rows in %.2fs",
                i, len(ranges), chunk_start, chunk_end, len(rates), elapsed,
            )
            frames.append(_rates_array_to_df(rates))

        if not frames:
            return _empty_rates_df()

        merged = pd.concat(frames, ignore_index=True)
        merged = self._correct_to_true_utc(merged)
        merged = merged.drop_duplicates(subset="time_utc").sort_values("time_utc").reset_index(drop=True)
        return merged

    def _last_closed_cutoff(self, timeframe: str) -> pd.Timestamp:
        now = pd.Timestamp.now(tz="UTC")
        tf_seconds = TIMEFRAME_SECONDS[timeframe]
        floor_epoch = (int(now.timestamp()) // tf_seconds) * tf_seconds
        return pd.Timestamp(floor_epoch, unit="s", tz="UTC")

    def _drop_incomplete(self, df: pd.DataFrame, timeframe: str, include_incomplete: bool) -> pd.DataFrame:
        if include_incomplete or df.empty:
            return df
        cutoff = self._last_closed_cutoff(timeframe)
        return df[df["time_utc"] < cutoff].reset_index(drop=True)

    def get_latest_rates(self, symbol: str, timeframe: str, count: int = 500,
                          include_incomplete: bool = False) -> pd.DataFrame:
        tf = _resolve_timeframe(timeframe)
        t0 = time_module.monotonic()
        # fetch a small buffer beyond `count` so dropping the forming candle still yields `count` closed bars
        fetch_count = count + 3
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, fetch_count)
        if rates is None:
            code, desc = mt5.last_error()
            raise MT5DataError(f"get_latest_rates({symbol!r}, {timeframe}) failed: [{code}] {desc}")
        df = _rates_array_to_df(rates)
        df = self._correct_to_true_utc(df)
        df = self._drop_incomplete(df, timeframe, include_incomplete)
        df = df.tail(count).reset_index(drop=True)
        logger.info(
            "get_latest_rates(%s, %s): %d rows in %.2fs",
            symbol, timeframe, len(df), time_module.monotonic() - t0,
        )
        return df

    def get_rates_incremental(self, symbol: str, timeframe: str, last_timestamp,
                               count: int = 500, include_incomplete: bool = False) -> pd.DataFrame:
        """
        Fetches bars forward from last_timestamp, capped at `count` per call.
        Deliberately keeps the OLDEST `count` bars (df.head), not the newest,
        when the gap exceeds `count` -- taking the newest bars would silently
        and permanently drop the older portion of the gap, since the caller's
        next call uses this call's max returned timestamp as its new
        last_timestamp and would never revisit the skipped range. Keeping the
        oldest bars means a caller that loops (like mt5_sync_service.py)
        naturally pages forward through a large gap across successive calls
        until it catches up, rather than jumping to "now" and abandoning the
        middle. Found via a real gap: an ~88.5h outage produced ~1062 missing
        M5 bars (>500), which the old `.tail(count)` truncated to the most
        recent 500 and permanently dropped the older ~562 -- M15/H1 were
        unaffected only because their bar counts over the same outage stayed
        under 500.
        """
        last_ts = _parse_time(last_timestamp)
        buffer_bars = 3
        start = last_ts - pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe] * buffer_bars)
        end = pd.Timestamp.now(tz="UTC")
        df = self.get_rates(symbol, timeframe, start, end)
        df = self._drop_incomplete(df, timeframe, include_incomplete)
        if len(df) > count:
            df = df.head(count).reset_index(drop=True)
        return df

    def get_multiple_timeframes(self, symbol: str, start, end) -> dict:
        return {tf: self.get_rates(symbol, tf, start, end) for tf in TIMEFRAME_MAP}

    def get_ticks(self, symbol: str, start, end, chunk_days=None) -> pd.DataFrame:
        start_utc = _parse_time(start)
        end_utc = _parse_time(end)
        broker_offset = self._require_calibration()  # see get_rates() for why this shift is needed

        ranges = [(start_utc, end_utc)]
        if chunk_days:
            ranges = []
            cursor = start_utc
            step = pd.Timedelta(days=chunk_days)
            while cursor < end_utc:
                chunk_end = min(cursor + step, end_utc)
                ranges.append((cursor, chunk_end))
                cursor = chunk_end

        frames = []
        for i, (chunk_start, chunk_end) in enumerate(ranges, start=1):
            ticks = mt5.copy_ticks_range(
                symbol,
                _to_naive_utc(chunk_start + broker_offset),
                _to_naive_utc(chunk_end + broker_offset),
                mt5.COPY_TICKS_ALL,
            )
            if ticks is None:
                code, desc = mt5.last_error()
                raise MT5DataError(
                    f"get_ticks chunk {i}/{len(ranges)} [{chunk_start} -> {chunk_end}] "
                    f"failed: [{code}] {desc}. This symbol/broker may not provide tick history."
                )
            logger.info(
                "Fetched tick chunk %d/%d [%s -> %s]: %d ticks",
                i, len(ranges), chunk_start, chunk_end, len(ticks),
            )
            frames.append(_ticks_array_to_df(ticks))

        if not frames:
            return _empty_ticks_df()

        merged = pd.concat(frames, ignore_index=True)
        merged = self._correct_to_true_utc(merged)
        merged = merged.drop_duplicates(subset="time_utc").sort_values("time_utc").reset_index(drop=True)
        return merged


def _build_arg_parser():
    p = argparse.ArgumentParser(description="MT5 data fetcher CLI (read-only)")
    p.add_argument("--symbol", default=os.environ.get("MT5_SYMBOL", "XAUUSD"))
    p.add_argument("--timeframe", default="M5", choices=sorted(TIMEFRAME_MAP))
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--count", type=int, default=500)
    p.add_argument("--output")
    p.add_argument("--include-incomplete", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p


def main():
    args = _build_arg_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    fetcher = MT5DataFetcher()
    try:
        fetcher.connect()
        account = fetcher.get_account_info()
        print(f"Account: login={account['login']} server={account['server']} balance={account['balance']}")

        fetcher.check_symbol(args.symbol)
        print(f"Symbol verified: {args.symbol}")

        if args.start and args.end:
            df = fetcher.get_rates(args.symbol, args.timeframe, args.start, args.end)
        else:
            df = fetcher.get_latest_rates(
                args.symbol, args.timeframe, count=args.count,
                include_incomplete=args.include_incomplete,
            )

        print(f"Rows fetched: {len(df)}")
        if not df.empty:
            print("First row:\n", df.iloc[0])
            print("Last row:\n", df.iloc[-1])

        if args.output and not df.empty:
            df.to_csv(args.output, index=False)
            print(f"Saved to {args.output}")
    finally:
        fetcher.disconnect()


if __name__ == "__main__":
    main()
