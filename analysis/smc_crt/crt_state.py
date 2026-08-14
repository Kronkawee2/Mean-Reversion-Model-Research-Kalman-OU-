"""
CRT State Engine (Phase 2b): persists Candle Range Theory concepts —
Asian session range levels, London/NY sweeps of those levels, and
Range Equilibrium (50%) — following the same additive-module pattern as
zone_state.py (Phase 2a). Does not touch crt_engine.py (still used as-is by
scoring.py's live pipeline); this module re-derives Asian range and sweep
detection itself because it needs a two-timeframe split crt_engine.py
doesn't make: session/sweep detection must run on h1 (session boundaries
are UTC-clock-defined and h4/h6/d1 candles straddle them, misrepresenting
the true session high/low and missing smaller sweeps), while Equilibrium
is a single-candle midpoint that belongs on h4/h6/d1 as originally planned.

State model (deliberately NOT a copy of SMC's active/mitigated/invalidated):

  - Asian range levels (one row per session per side: 'asian_range_high' /
    'asian_range_low') DO fit a lifecycle, but a two-state one, not
    three-state: a level starts 'pending' (untested) and is either 'swept'
    (a London/NY h1 candle wicks through it and closes back inside the
    Asian range — the manipulation is complete, which is a terminal,
    one-time event, not a "then what" state like SMC's mitigated) or, if no
    h1 candle sweeps it before the next Asian session begins, 'expired'
    (the level's day is over; it stops being a live liquidity target).
    There is no "mitigated" in between: a sweep is a single-bar wick+close
    event, not a zone that can be partially touched and later invalidated.
    sweep_direction records the resulting bias ('bullish' for a swept low,
    'bearish' for a swept high) for the one row that got swept.

  - Range Equilibrium has no lifecycle at all: it's a deterministic
    per-candle computed value ((high+low)/2 of that single h4/h6/d1
    candle), not a zone that gets created and later touched/broken. Each
    equilibrium row is a snapshot fact about one candle, so `state` is
    NULL for these rows and premium/discount is stored as a plain
    classification (`zone_bias`) of that candle's close, not a state
    transition.
"""

import numpy as np
import pandas as pd

ASIAN_START_HOUR = 0
ASIAN_END_HOUR = 6

CRT_SIGNAL_COLUMNS = [
    "symbol", "timeframe", "signal_type", "session_date", "bar_datetime",
    "level_price", "range_high", "range_low", "equilibrium_price", "zone_bias",
    "state", "sweep_direction", "swept_at_bar", "expired_at_bar",
]


class CRTStateEngine:
    """Derives Asian range / sweep state and Range Equilibrium signals for persistence."""

    def __init__(self, asian_start_hour: int = ASIAN_START_HOUR, asian_end_hour: int = ASIAN_END_HOUR):
        self.asian_start_hour = asian_start_hour
        self.asian_end_hour = asian_end_hour

    # ------------------------------------------------------------------
    # Asian range + London/NY sweep (h1 input)
    # ------------------------------------------------------------------

    def detect_asian_sweeps(self, df: pd.DataFrame, symbol: str, timeframe: str = "h1") -> pd.DataFrame:
        """
        df: h1 OHLC with price_datetime, high_price, low_price, close_price,
        sorted ascending. Returns two rows per session day (asian_range_high,
        asian_range_low) with pending/swept/expired state.
        """
        if df.empty:
            return pd.DataFrame(columns=CRT_SIGNAL_COLUMNS)

        base = df.reset_index(drop=True).copy()
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])
        base["date"] = base["price_datetime"].dt.date
        base["hour"] = base["price_datetime"].dt.hour

        asian_mask = (base["hour"] >= self.asian_start_hour) & (base["hour"] < self.asian_end_hour)
        sessions = (
            base[asian_mask]
            .groupby("date")
            .agg(asian_high=("high_price", "max"), asian_low=("low_price", "min"))
            .reset_index()
            .sort_values("date")
        )

        rows = []
        dates = base["date"].values
        hours = base["hour"].values
        highs = base["high_price"].values
        lows = base["low_price"].values
        closes = base["close_price"].values
        dts = base["price_datetime"].values
        n = len(base)

        session_dates = list(sessions["date"])
        for si, session_row in sessions.iterrows():
            sess_date = session_row["date"]
            ah = session_row["asian_high"]
            al = session_row["asian_low"]
            session_dt = pd.Timestamp(sess_date)

            # Post-session window: bars from this session's own date (hour >=
            # asian_end_hour) up to (but not including) the next session's
            # start. A level not swept anywhere in that window has expired.
            idx_of = np.where(dates == sess_date)[0]
            post_start = idx_of[0] if len(idx_of) else None
            # scan bound: first bar of the next date that has its own Asian
            # session, else end of data
            pos = session_dates.index(sess_date)
            next_sess_date = session_dates[pos + 1] if pos + 1 < len(session_dates) else None

            high_state, high_swept_at = "pending", None
            low_state, low_swept_at = "pending", None

            for j in range(post_start if post_start is not None else 0, n):
                if dates[j] == sess_date and hours[j] < self.asian_end_hour:
                    continue
                if next_sess_date is not None and dates[j] >= next_sess_date:
                    break

                if high_state == "pending" and highs[j] > ah and closes[j] <= ah:
                    high_state, high_swept_at = "swept", dts[j]
                if low_state == "pending" and lows[j] < al and closes[j] >= al:
                    low_state, low_swept_at = "swept", dts[j]

                if high_state != "pending" and low_state != "pending":
                    break

            expired_at = None
            if next_sess_date is not None:
                next_idx = np.where(dates == next_sess_date)[0]
                if len(next_idx):
                    expired_at = dts[next_idx[0]]

            if high_state == "pending" and expired_at is not None:
                high_state = "expired"
            if low_state == "pending" and expired_at is not None:
                low_state = "expired"

            rows.append({
                "symbol": symbol, "timeframe": timeframe, "signal_type": "asian_range_high",
                "session_date": sess_date, "bar_datetime": session_dt,
                "level_price": float(ah), "range_high": None, "range_low": None,
                "equilibrium_price": None, "zone_bias": None,
                "state": high_state,
                "sweep_direction": "bearish" if high_state == "swept" else None,
                "swept_at_bar": pd.Timestamp(high_swept_at) if high_swept_at is not None else None,
                "expired_at_bar": pd.Timestamp(expired_at) if (high_state == "expired" and expired_at is not None) else None,
            })
            rows.append({
                "symbol": symbol, "timeframe": timeframe, "signal_type": "asian_range_low",
                "session_date": sess_date, "bar_datetime": session_dt,
                "level_price": float(al), "range_high": None, "range_low": None,
                "equilibrium_price": None, "zone_bias": None,
                "state": low_state,
                "sweep_direction": "bullish" if low_state == "swept" else None,
                "swept_at_bar": pd.Timestamp(low_swept_at) if low_swept_at is not None else None,
                "expired_at_bar": pd.Timestamp(expired_at) if (low_state == "expired" and expired_at is not None) else None,
            })

        return pd.DataFrame(rows, columns=CRT_SIGNAL_COLUMNS) if rows else pd.DataFrame(columns=CRT_SIGNAL_COLUMNS)

    # ------------------------------------------------------------------
    # Range Equilibrium (h4/h6/d1 input)
    # ------------------------------------------------------------------

    def calc_equilibrium(self, df: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        df: h4/h6/d1 OHLC with price_datetime, high_price, low_price,
        close_price. Returns one row per candle: 50% equilibrium level and
        premium/discount classification of that candle's own close.
        """
        if df.empty:
            return pd.DataFrame(columns=CRT_SIGNAL_COLUMNS)

        base = df.reset_index(drop=True).copy()
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])
        base["high_price"] = base["high_price"].astype(float)
        base["low_price"] = base["low_price"].astype(float)
        base["close_price"] = base["close_price"].astype(float)

        eq = (base["high_price"] + base["low_price"]) / 2.0
        bias = np.where(base["close_price"] > eq, "premium", "discount")

        out = pd.DataFrame({
            "symbol": symbol, "timeframe": timeframe, "signal_type": "equilibrium",
            "session_date": None, "bar_datetime": base["price_datetime"],
            "level_price": None,
            "range_high": base["high_price"].astype(float),
            "range_low": base["low_price"].astype(float),
            "equilibrium_price": eq.astype(float),
            "zone_bias": bias,
            "state": None, "sweep_direction": None,
            "swept_at_bar": None, "expired_at_bar": None,
        })
        return out[CRT_SIGNAL_COLUMNS]
