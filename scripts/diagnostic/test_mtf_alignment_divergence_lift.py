"""
Empirical pre-check for MTF Alignment Divergence (HTF Hidden Divergence
confluence with LTF Regular Divergence, indicator-matched) — run BEFORE
building any persistence pipeline for this model, per this project's
standard of validating a design against real data before implementing it
(same discipline as CONFIRMATION_WINDOW_BARS, STRUCTURAL_TP_FRACTION, the
SMC 720-bar window, etc.).

RESULT (2026-08, gold + EURUSD, RSI/OBV/Stochastic/CCI): NO indicator x
symbol combination showed a meaningful positive real-vs-random-null lift
at any operationally useful window (5h-320h). The best result across all
5 combinations tested was Stochastic/XAUUSD at N=10h (lift=+0.036), which
is small, inconsistent with the rest of that same indicator's own curve
(goes negative immediately at N=20h), and well within noise for a 79-event
sample. All 5 combinations converge to near-zero lift only at the
trivially wide 480-720h (20-30 day) range, where event density alone makes
overlap nearly inevitable regardless of any real relationship -- not a
"confluence window" in any tradeable sense.

DECISION: MTF Alignment Divergence is deferred, not built. See
analysis/divergence/technical_divergence_state.py's "Explicitly deferred"
section and docs/DECISIONS.md for the full writeup. This script is kept so
the test can be re-run later (more history accumulates, a different
symbol/indicator is of interest, or someone wants to sanity-check the
methodology itself) without re-deriving it from scratch.

METHODOLOGY: for each HTF (h1) Hidden Divergence event of a given
indicator, check whether a matching-DIRECTION LTF (m15) Regular Divergence
event (same indicator -- indicator-matched alignment, confirmed with the
user over cross-indicator matching, for interpretability) lands within a
candidate window [htf_bar, htf_bar + N hours]. Compare the resulting
"real" match rate against a NULL baseline: the same count of LTF events,
timestamps drawn uniformly at random across the same span, averaged over
many trials. A window only counts as evidence of genuine confluence if the
real match rate clears the null rate by a meaningful margin -- otherwise
the "match" is just what you'd expect from two independent event streams
of that density, not a real timing relationship.

Pivot windows used: h1=3 (existing, established convention), m15=12 (time-
matched to h1's ~3-hour pivot window: 3h / 15min = 12 bars -- see the MTF
Alignment Divergence design-phase report for why blind-copying h1's
pivot_window=3 to m15 was rejected, it over-produces pivots ~4x h1's rate).

Usage:
    python scripts/diagnostic/test_mtf_alignment_divergence_lift.py
    python scripts/diagnostic/test_mtf_alignment_divergence_lift.py --symbol EURUSD --indicator obv
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.divergence.technical_divergence_state import TechnicalDivergenceEngine  # noqa: E402

load_dotenv()

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3308"))
DB_USER = os.environ.get("DB_USER", "quant_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

RAW_DB = {"XAUUSD": "raw_gold", "EURUSD": "raw_eurusd"}
SILVER_DB = {"XAUUSD": "curated_gold", "EURUSD": "curated_eurusd"}
INDICATOR_COLS = {"rsi": "rsi_14", "obv": "obv", "stochastic": "stoch_k", "cci": "cci_20"}

CANDIDATE_WINDOWS_HOURS = (5, 10, 20, 40, 80, 160, 240, 320, 480, 720)
N_RANDOM_TRIALS = 100


def _conn(database):
    return pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=database, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )


def _load(raw_db, curated_db, timeframe, symbol, indicator_col):
    conn = _conn(raw_db)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT price_datetime, close_price FROM `{timeframe}` ORDER BY price_datetime")
            price = pd.DataFrame(cur.fetchall())
    finally:
        conn.close()

    conn = _conn(curated_db)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT bar_datetime AS price_datetime, {indicator_col} FROM features "
                "WHERE symbol=%s AND timeframe=%s ORDER BY bar_datetime",
                (symbol, timeframe),
            )
            ind = pd.DataFrame(cur.fetchall())
    finally:
        conn.close()

    merged = pd.merge(price, ind, on="price_datetime", how="inner")
    merged["close_price"] = merged["close_price"].astype(float)
    merged[indicator_col] = merged[indicator_col].astype(float)
    return merged.sort_values("price_datetime").reset_index(drop=True)


def lift_test(symbol, divergence_type, h1_window=3, m15_window=12,
              candidates=CANDIDATE_WINDOWS_HOURS, n_random_trials=N_RANDOM_TRIALS, seed=0):
    raw_db, curated_db = RAW_DB[symbol], SILVER_DB[symbol]
    indicator_col = INDICATOR_COLS[divergence_type]

    h1 = _load(raw_db, curated_db, "h1", symbol, indicator_col)
    m15 = _load(raw_db, curated_db, "m15", symbol, indicator_col)

    htf_sig = TechnicalDivergenceEngine(pivot_window=h1_window).detect(
        h1, symbol=symbol, timeframe="h1", indicator_col=indicator_col, divergence_type=divergence_type
    )
    htf_hidden = htf_sig[htf_sig["divergence_class"] == "hidden"].sort_values("bar_datetime").reset_index(drop=True)

    ltf_sig = TechnicalDivergenceEngine(pivot_window=m15_window).detect(
        m15, symbol=symbol, timeframe="m15", indicator_col=indicator_col, divergence_type=divergence_type
    )
    ltf_regular = ltf_sig[ltf_sig["divergence_class"] == "regular"].sort_values("bar_datetime").reset_index(drop=True)

    m15_start, m15_end = m15["price_datetime"].min(), m15["price_datetime"].max()
    htf_hidden = htf_hidden[(htf_hidden["bar_datetime"] >= m15_start) & (htf_hidden["bar_datetime"] <= m15_end)].reset_index(drop=True)

    n_htf, n_ltf = len(htf_hidden), len(ltf_regular)
    if n_htf == 0 or n_ltf == 0:
        return {"symbol": symbol, "indicator": divergence_type, "n_htf": n_htf, "n_ltf": n_ltf,
                "best_N": None, "best_lift": None, "results": []}

    span_hours = (m15_end - m15_start).total_seconds() / 3600.0
    rng = np.random.default_rng(seed)
    results = []

    for N in candidates:
        real_matches = 0
        for _, h in htf_hidden.iterrows():
            window_end = h["bar_datetime"] + pd.Timedelta(hours=N)
            matches = ltf_regular[(ltf_regular["direction"] == h["direction"]) &
                                   (ltf_regular["bar_datetime"] >= h["bar_datetime"]) &
                                   (ltf_regular["bar_datetime"] <= window_end)]
            if not matches.empty:
                real_matches += 1
        real_rate = real_matches / n_htf

        null_rates = []
        for _ in range(n_random_trials):
            rand_offsets = rng.uniform(0, span_hours, size=n_ltf)
            rand_times_sorted = np.sort((m15_start + pd.to_timedelta(rand_offsets, unit="h")).values)
            cnt = 0
            for _, h in htf_hidden.iterrows():
                lo = np.datetime64(h["bar_datetime"])
                hi = np.datetime64(h["bar_datetime"] + pd.Timedelta(hours=N))
                idx = np.searchsorted(rand_times_sorted, lo)
                if idx < len(rand_times_sorted) and rand_times_sorted[idx] <= hi:
                    cnt += 1
            null_rates.append(cnt / n_htf)
        null_mean = float(np.mean(null_rates))
        results.append((N, real_rate, null_mean, real_rate - null_mean))

    best = max(results, key=lambda r: r[3])
    return {"symbol": symbol, "indicator": divergence_type, "n_htf": n_htf, "n_ltf": n_ltf,
            "best_N": best[0], "best_lift": best[3], "results": results}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, choices=list(RAW_DB) + [None])
    parser.add_argument("--indicator", default=None, choices=list(INDICATOR_COLS) + [None])
    args = parser.parse_args()

    combos = [(s, i) for s in (["XAUUSD", "EURUSD"] if args.symbol is None else [args.symbol])
              for i in (list(INDICATOR_COLS) if args.indicator is None else [args.indicator])]

    summary = []
    for symbol, indicator in combos:
        print(f"\n=== {symbol} / {indicator} ===")
        r = lift_test(symbol, indicator)
        print(f"  n_htf_hidden={r['n_htf']}  n_ltf_regular={r['n_ltf']}")
        for N, real, null, lift in r["results"]:
            marker = "  <-- best" if N == r["best_N"] else ""
            print(f"    N={N:4d}h  real={real:.3f}  null={null:.3f}  lift={lift:+.3f}{marker}")
        summary.append(r)

    print("\n\n=== SUMMARY ===")
    for r in summary:
        if r["best_N"] is None:
            print(f"{r['symbol']:8s} {r['indicator']:12s} insufficient events (n_htf={r['n_htf']}, n_ltf={r['n_ltf']})")
            continue
        meaningful = r["best_lift"] is not None and r["best_lift"] > 0.05
        print(f"{r['symbol']:8s} {r['indicator']:12s} n_htf={r['n_htf']:3d} n_ltf={r['n_ltf']:3d}  "
              f"best_N={r['best_N']}  best_lift={r['best_lift']:+.3f}  meaningful_positive={meaningful}")


if __name__ == "__main__":
    main()
