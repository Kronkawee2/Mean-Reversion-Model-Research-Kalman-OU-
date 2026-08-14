"""
Compares static (clock-based) vs dynamic (6h-bucket, sweep-driven) session
weighting over the same real gold h1 window. Purely a read/compare tool —
does not write to the database (dynamic mode's session labels don't fit
htf_bias's session ENUM, and this is a decision-support comparison, not a
production run).

Usage:
    python scripts/diagnostic/compare_session_weighting_modes.py --symbol XAUUSD
"""

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
import pymysql
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from analysis.strategies.htf_bias_engine import HTFBiasEngine  # noqa: E402
from scripts.detection.run_htf_bias_detection import (  # noqa: E402
    RAW_DB, SILVER_DB, load_h1_bars, load_smc_zones, load_crt_equilibrium,
    load_features_h1, load_volume_profile, load_divergence_h1, load_liquidity_sweeps,
)

load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="XAUUSD", choices=list(RAW_DB))
    args = parser.parse_args()
    symbol = args.symbol

    print(f"Loading {symbol} inputs from `{RAW_DB[symbol]}` / `{SILVER_DB[symbol]}`...")
    h1_bars = load_h1_bars(symbol)
    if h1_bars.empty:
        print(f"No h1 data available for {symbol} — nothing to do.")
        return
    smc_zones = load_smc_zones(symbol)
    crt_equilibrium = load_crt_equilibrium(symbol)
    features_h1 = load_features_h1(symbol)
    volume_profile = load_volume_profile(symbol)
    divergence_h1 = load_divergence_h1(symbol)
    liquidity_sweeps = load_liquidity_sweeps(symbol)
    print(f"Loaded {len(h1_bars)} h1 bars, {len(liquidity_sweeps)} liquidity sweeps.")

    engine = HTFBiasEngine()
    static = engine.compute_bias(
        h1_bars, smc_zones, crt_equilibrium, features_h1, volume_profile, divergence_h1, liquidity_sweeps,
        symbol=symbol, timeframe="h1", session_weighting_mode="static",
    )
    dynamic = engine.compute_bias(
        h1_bars, smc_zones, crt_equilibrium, features_h1, volume_profile, divergence_h1, liquidity_sweeps,
        symbol=symbol, timeframe="h1", session_weighting_mode="dynamic",
    )

    merged = static.merge(
        dynamic, on="bar_datetime", suffixes=("_static", "_dynamic")
    )

    print(f"\nTotal bars compared: {len(merged)}")
    print("\nStatic bias distribution:")
    print(static["bias"].value_counts().to_string())
    print("\nDynamic bias distribution:")
    print(dynamic["bias"].value_counts().to_string())

    disagree = merged[merged["bias_static"] != merged["bias_dynamic"]].copy()
    print(f"\n{'=' * 70}")
    print(f"BIAS LABEL DISAGREEMENTS: {len(disagree)} / {len(merged)} bars")
    print(f"{'=' * 70}")
    cols = [
        "bar_datetime", "bias_static", "confluence_score_static", "session_static", "session_multiplier_static",
        "bias_dynamic", "confluence_score_dynamic", "session_dynamic", "session_multiplier_dynamic",
        "crt_contribution_static", "liquidity_sweep_contribution_static",
    ]
    for _, row in disagree.iterrows():
        print(
            f"  {row['bar_datetime']}  "
            f"STATIC={row['bias_static']:8s}({row['confluence_score_static']:7.2f}, {row['session_static']:8s} x{row['session_multiplier_static']})  "
            f"DYNAMIC={row['bias_dynamic']:8s}({row['confluence_score_dynamic']:7.2f}, {row['session_dynamic']:16s} x{row['session_multiplier_dynamic']})  "
            f"crt={row['crt_contribution_static']:+.1f}  sweep={row['liquidity_sweep_contribution_static']:+.1f}"
        )

    # Flag 1: genuine Asian-session (00:00-06:00 UTC) sweep, static
    # underweighted it (asian x0.8) but dynamic elevated it (x1.2) --
    # and that difference actually moved the bias label.
    asian_hours = disagree["bar_datetime"].dt.hour.between(0, 5)
    dynamic_elevated = disagree["session_dynamic"].str.contains("elevated", na=False)
    static_was_asian = disagree["session_static"] == "asian"
    flag1 = disagree[asian_hours & dynamic_elevated & static_was_asian]
    print(f"\n{'=' * 70}")
    print(f"FLAG 1 — Asian-session sweep underweighted by static, corrected by dynamic: {len(flag1)} bars")
    print(f"{'=' * 70}")
    for _, row in flag1.iterrows():
        print(f"  {row['bar_datetime']}  static={row['bias_static']}({row['confluence_score_static']:.2f})  "
              f"dynamic={row['bias_dynamic']}({row['confluence_score_dynamic']:.2f})")

    # Flag 2: dynamic elevated a bucket off a single (possibly borderline)
    # sweep and that flip looks aggressive relative to static's steadier
    # read -- report bars where dynamic's bias is MORE extreme (further
    # from neutral) than static's, as candidates for "overweighted."
    def _severity(b, s):
        return 0 if b == "neutral" else abs(s)
    disagree["severity_static"] = [_severity(b, s) for b, s in zip(disagree["bias_static"], disagree["confluence_score_static"])]
    disagree["severity_dynamic"] = [_severity(b, s) for b, s in zip(disagree["bias_dynamic"], disagree["confluence_score_dynamic"])]
    flag2 = disagree[(disagree["severity_dynamic"] > disagree["severity_static"]) & (disagree["session_dynamic"].str.contains("elevated", na=False))]
    print(f"\n{'=' * 70}")
    print(f"FLAG 2 — dynamic mode MORE extreme than static off an elevated bucket: {len(flag2)} bars")
    print(f"{'=' * 70}")
    for _, row in flag2.iterrows():
        print(f"  {row['bar_datetime']}  static={row['bias_static']}({row['confluence_score_static']:.2f})  "
              f"dynamic={row['bias_dynamic']}({row['confluence_score_dynamic']:.2f})  session_dynamic={row['session_dynamic']}")


if __name__ == "__main__":
    main()
