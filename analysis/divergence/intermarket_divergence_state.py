"""
Inter-market Divergence Engine: builds inter-market divergence fresh on
top of the proven Category 2 technical-divergence framework
(find_price_pivots / classify_divergence / TechnicalDivergenceEngine),
rather than rehabilitating detect_intermarket_divergence /
detect_cot_divergence in detection.py. Per the Phase 2h survey: those
existing functions aren't actually pivot-based despite their docstrings
claiming HH/LL logic (a fixed-lag two-point comparison instead), fire on
32% of all bars on real gold-vs-DXY d1 data (unusable as a discrete
signal), and detect_cot_divergence has no persisted data source, a silent
fake-data fallback on fetch failure, and a lookback-window granularity
bug — none of that is reused here.

Phase 2h shipped the 4 models with data already available: XAU vs DXY,
EUR vs DXY, XAU vs US10Y, XAU vs GDX. Phase 2i adds the final 3: COT gold,
COT EUR (both from the new fetcher/cot_fetcher.py), and XAU vs SPDR GLD
holdings (fetcher/spdr_fetcher.py) — completing the original divergence
matrix. A later round added 5 more once real free data sources were
found: XAU vs GPR (fetcher/gpr_fetcher.py), XAU vs XAG/silver
(fetcher/market_fetcher.py's SILVER), XAU vs TIPS real yield and XAU vs
Fed Funds rate (fetcher/fred_fetcher.py), XAU vs CPI (also
fred_fetcher.py), and finally EUR vs yield-spread (fetcher/ecb_fetcher.py
+ raw_us10y, US10Y-EU10Y) — closing what this docstring used to list as
deferred indefinitely for lack of a EU/German yield source; the ECB Data
Portal's public SDMX API turned out to have exactly the daily series
needed, just not previously looked for.

Timeframe: d1 for the primary asset in every model. raw_gold/raw_eurusd/
raw_dxy/raw_us10y/raw_gdx all have deep, clean d1 history over the
relevant overlap windows (verified before building in Phase 2h). h1 was
ruled out: raw_gold.h1 only has ~5 weeks of MT5-sourced history, which
would cap every h1 comparison regardless of the driver's own depth.

Design: the driver's value is treated exactly like an "indicator column"
fed into TechnicalDivergenceEngine.detect() — the same mechanism already
proven for RSI/OBV/Stochastic/CCI, then extended to DXY/US10Y/GDX price
in Phase 2h. The primary asset's own price pivots are found as usual; the
driver's value at those same pivot bars stands in for "the indicator's
value." No changes to TechnicalDivergenceEngine were needed for Phase 2h,
and none were needed for Phase 2i either — COT (weekly) and SPDR (daily)
both merge onto the primary asset's daily price via the same
merge_asof(direction="backward") pattern already used for DXY/US10Y/GDX;
see run_intermarket_divergence_detection.py's DRIVER_SOURCE config for
how each source's (database, table, date column, value column) differs.
COT being weekly needed no special pivot-timing scheme — merging its
value onto the daily price series (backward-filled until the next
report, same causal principle as every other driver) means the existing
day-level pivot logic applies unchanged, which is also why the old
detect_cot_divergence's lookback-window granularity bug doesn't apply
here: there's no rolling lookback in this design at all, just pivot pairs.

Relationship-aware sign handling (the one thing genuinely different from
a computed same-direction indicator like RSI): classify_divergence's
bullish/bearish semantics assume the indicator normally moves WITH price,
the way RSI does — a low-pivot pair where the indicator makes a higher
low while price makes a lower low reads as bullish because that pattern
means "the same-direction companion is refusing to confirm the new low."
For an *inverse* pair (gold vs DXY, EUR vs DXY, gold vs US10Y, and COT's
commercial net position vs price — commercials increase shorts as price
rises, i.e. commercial_net_position normally moves opposite to price),
that assumption is backwards: feeding the driver's raw value in
unmodified would invert the economic meaning of every label. The fix is
to negate the driver's value before pivot-comparison for inverse pairs —
a negated DXY (or negated commercial net position) behaves, directionally,
like a synthetic "gold-supportive" series, so the same-direction logic
built for RSI applies correctly again — then flip the sign back on the
persisted pivot indicator values afterward, so what gets stored/reported
is the driver's real value (an actual DXY level, or an actual COT
commercial net position you can check against CFTC.gov), not the negated
intermediate used only for classification. For *direct* pairs (gold vs
GDX, gold vs SPDR holdings — GLD holdings normally rise alongside gold
demand/price, the same direction), no sign flip is applied at all.
"""

import pandas as pd

from .technical_divergence_state import TechnicalDivergenceEngine, DIVERGENCE_SIGNAL_COLUMNS

# divergence_type -> relationship ('inverse': driver normally moves
# opposite to the primary asset; 'direct': driver normally moves with it)
INTERMARKET_MODELS = {
    "xau_dxy": {"primary": "XAUUSD", "relationship": "inverse"},
    "eur_dxy": {"primary": "EURUSD", "relationship": "inverse"},
    "xau_us10y": {"primary": "XAUUSD", "relationship": "inverse"},
    "xau_gdx": {"primary": "XAUUSD", "relationship": "direct"},
    "cot_gold": {"primary": "XAUUSD", "relationship": "inverse"},
    "cot_eur": {"primary": "EURUSD", "relationship": "inverse"},
    "xau_spdr": {"primary": "XAUUSD", "relationship": "direct"},
    # Safe-haven theory: gold demand/price normally rises alongside
    # geopolitical risk (same direction as GDX/SPDR holdings), not opposite
    # it like DXY/US10Y -- flagged for a real-data sanity check once this
    # model has live signals, same as every other relationship here.
    "xau_gpr": {"primary": "XAUUSD", "relationship": "direct"},
    # Precious metals co-movement: confirmed against real raw_gold/
    # raw_silver d1 history before wiring this in (not just asserted from
    # theory) -- price-level correlation 0.93, daily-return correlation
    # 0.78 across 6,512 matched bars. Direct, same as GDX/SPDR.
    "xau_xag": {"primary": "XAUUSD", "relationship": "direct"},
    # Real-yield opportunity-cost theory (the single most commonly cited
    # macro driver of gold in the literature): gold has no yield of its
    # own, so a rising real rate raises the opportunity cost of holding it
    # -- inverse. CONFIRMED against real raw_gold/raw_fred history:
    # price-level correlation -0.10, daily-change correlation -0.20 across
    # 5,888 matched bars (weaker than DXY/GDX but directionally consistent
    # and the strongest signal of the two FRED series added at the same
    # time -- see xau_fedfunds below for the one that did NOT confirm).
    "xau_tips": {"primary": "XAUUSD", "relationship": "inverse"},
    # Same opportunity-cost theory as TIPS above (higher nominal rates ->
    # higher cost of holding non-yielding gold -> inverse), but UNLIKE
    # xau_tips this did NOT confirm empirically: price-level correlation
    # +0.10, daily-change correlation +0.03 against real raw_gold/raw_fred
    # history across 6,512 matched bars -- essentially no relationship,
    # not even weakly inverse. Wired as inverse anyway on theory (real
    # yields, not the nominal fed funds rate, are the more direct/complete
    # driver -- fed funds alone omits inflation expectations, which is
    # plausibly why TIPS confirmed and this didn't) -- but this is a
    # theory-based, not data-confirmed, relationship. Treat xau_fedfunds
    # signals with more skepticism than any other model in this dict until
    # there's a better empirical basis for its sign.
    "xau_fedfunds": {"primary": "XAUUSD", "relationship": "inverse"},
    # Inflation-hedge theory: gold is conventionally held to track/outpace
    # CPI over time -- direct. Checked against real raw_gold/raw_fred
    # history (6,513 bars, merge_asof-forward-filled monthly CPI onto
    # daily price, same as the real detection path): price-level
    # correlation +0.90 -- but both series have been in a shared secular
    # uptrend for the entire sample, which inflates level correlation
    # between almost any two long-run-rising series regardless of true
    # relationship (the same non-stationary-trend caveat noted for
    # xau_fedfunds's level correlation). The more diagnostic same-
    # frequency return correlation is +0.03 -- inconclusive, though this
    # number is on shakier ground than xau_fedfunds's equivalent: CPI only
    # updates 12x/year, so its daily pct_change is ~0 for weeks between
    # releases, diluting the comparison against gold's true daily returns.
    # Wired as direct on theory, same treatment as xau_fedfunds -- not
    # data-confirmed, treat with matching skepticism.
    "xau_cpi": {"primary": "XAUUSD", "relationship": "direct"},
    # FX carry-trade theory: when US yields exceed EU yields (the spread
    # rises), USD strengthens relative to EUR -> EURUSD falls -- inverse.
    # CONFIRMED cleanly against real raw_eurusd/raw_us10y/raw_ecb history:
    # price-level correlation -0.79, daily-change correlation -0.07 across
    # 5,676 matched bars (see run_intermarket_divergence_detection.py's
    # _load_yield_spread() for how the driver itself, US10Y-EU10Y, is
    # computed from two raw sources rather than read from one table like
    # every other model here). The strongest and cleanest-signed
    # correlation of any driver added this round -- closes the "EUR vs
    # yield-spread" item this module's docstring above previously listed
    # as deferred indefinitely for lack of a EU/German yield source.
    "eur_yield_spread": {"primary": "EURUSD", "relationship": "inverse"},
}


class IntermarketDivergenceEngine:
    """Detects Regular + Hidden inter-market divergence between a primary asset and a driver, reusing TechnicalDivergenceEngine."""

    def __init__(self, pivot_window: int = 3):
        self.engine = TechnicalDivergenceEngine(pivot_window=pivot_window)

    def detect(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        divergence_type: str,
        relationship: str,
        driver_col: str = "driver_close",
    ) -> pd.DataFrame:
        """
        df: merged primary+driver data with price_datetime, close_price
        (the primary asset), and `driver_col` (the driver's close price),
        sorted ascending. relationship: 'inverse' or 'direct'.
        """
        if relationship not in ("inverse", "direct"):
            raise ValueError(f"relationship must be 'inverse' or 'direct', got {relationship!r}")
        if df.empty or driver_col not in df.columns:
            return pd.DataFrame(columns=DIVERGENCE_SIGNAL_COLUMNS)

        sign = -1.0 if relationship == "inverse" else 1.0
        base = df.copy()
        base["_driver_signal"] = sign * base[driver_col]

        signals = self.engine.detect(
            base, symbol=symbol, timeframe=timeframe,
            indicator_col="_driver_signal", divergence_type=divergence_type,
        )
        if signals.empty:
            return signals

        # Undo the sign flip: persisted/reported indicator values are the
        # driver's real price, not the negated classification intermediate.
        signals = signals.copy()
        signals["prev_pivot_indicator"] = sign * signals["prev_pivot_indicator"]
        signals["curr_pivot_indicator"] = sign * signals["curr_pivot_indicator"]
        return signals
