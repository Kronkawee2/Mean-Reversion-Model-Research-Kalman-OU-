"""
Session Volume Profile Engine (Phase 2d): turns the existing
VolumeProfileCalculator (histogram binning, POC, Value Area, HVN/LVN —
unchanged except for the HVN/LVN local-extrema fix documented in
calculator.py) into one profile per UTC calendar day, for persistence.

Scope decisions (confirmed with the user before building, not assumed):
  - Timeframe: h1 only. Both raw_gold and raw_eurusd have an h1 table;
    raw_eurusd.h1 is currently empty (a pre-existing gap from Phase 2b/2c,
    not something this module can fix), so EURUSD session profiles will
    be empty until that gap is closed.
  - Calculation window: one profile per UTC calendar day ("session"),
    computed only from that day's h1 bars — the classic Steidlmayer
    Market Profile convention of a profile per trading session, and
    consistent with the UTC-day boundary CRT's Asian session already
    uses (Phase 2b). This is NOT a rolling window recalculated on every
    bar; a day with too few bars to form a meaningful histogram (fewer
    than MIN_BARS_PER_SESSION) is skipped rather than producing a
    degenerate profile.
  - Volume source: both MT5-sourced and Yahoo-sourced raw tables already
    normalize to a single `volume` column upstream (mt5_sync_service.py
    maps MT5's tick_volume into it, yahoo_finance_client.py maps Yahoo's
    Volume into it — see schema_raw.sql). This module just reads
    `volume` directly; no column-name resolution needed here.
  - Each bar's entire volume is bucketed at that bar's close price (not
    split across the bar's high-low range) — the same simplification
    VolumeProfileCalculator already used for the live dashboard's VPOC
    zone, kept consistent rather than introducing a second, different
    binning method for the same underlying calculator.
"""

import pandas as pd

from .calculator import VolumeProfileCalculator

MIN_BARS_PER_SESSION = 4

VOLUME_PROFILE_COLUMNS = [
    "symbol", "timeframe", "session_date", "bin_index",
    "bin_low", "bin_high", "bin_center", "bin_volume",
    "is_poc", "in_value_area", "is_hvn", "is_lvn",
    "session_poc", "session_vah", "session_val", "session_total_volume", "num_bins",
]


class SessionVolumeProfileEngine:
    """Computes one Volume Profile per UTC session day from h1 OHLCV, bin-row output for persistence."""

    def __init__(self, num_bins: int = 50, value_area_pct: float = 0.70):
        self.num_bins = num_bins
        self.calc = VolumeProfileCalculator(num_bins=num_bins, value_area_pct=value_area_pct)

    def compute_session_profiles(self, df: pd.DataFrame, symbol: str, timeframe: str = "h1") -> pd.DataFrame:
        """
        df: h1 OHLCV with price_datetime, close_price, volume, sorted
        ascending. Returns one row per bin per session day.
        """
        if df.empty:
            return pd.DataFrame(columns=VOLUME_PROFILE_COLUMNS)

        base = df.reset_index(drop=True).copy()
        base["price_datetime"] = pd.to_datetime(base["price_datetime"])
        base["session_date"] = base["price_datetime"].dt.date
        if "volume" not in base.columns:
            base["volume"] = 1.0

        rows = []
        for session_date, day_df in base.groupby("session_date"):
            if len(day_df) < MIN_BARS_PER_SESSION:
                continue

            profile = self.calc.compute_profile(day_df)
            if "bin_centers" not in profile:
                continue

            bins = profile["bins"]
            bin_centers = profile["bin_centers"]
            bin_volumes = profile["bin_volumes"]
            poc_idx = profile["poc_idx"]
            va_left = profile["va_left_idx"]
            va_right = profile["va_right_idx"]
            hvn_set = set(profile["hvn_indices"])
            lvn_set = set(profile["lvn_indices"])

            for i in range(len(bin_centers)):
                rows.append({
                    "symbol": symbol, "timeframe": timeframe, "session_date": session_date,
                    "bin_index": i,
                    "bin_low": float(bins[i]), "bin_high": float(bins[i + 1]),
                    "bin_center": float(bin_centers[i]), "bin_volume": float(bin_volumes[i]),
                    "is_poc": (i == poc_idx),
                    "in_value_area": (va_left <= i <= va_right),
                    "is_hvn": (i in hvn_set),
                    "is_lvn": (i in lvn_set),
                    "session_poc": profile["poc"], "session_vah": profile["vah"], "session_val": profile["val"],
                    "session_total_volume": profile["total_volume"], "num_bins": self.num_bins,
                })

        return pd.DataFrame(rows, columns=VOLUME_PROFILE_COLUMNS) if rows else pd.DataFrame(columns=VOLUME_PROFILE_COLUMNS)
