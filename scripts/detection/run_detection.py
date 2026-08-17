"""
Runs the full curated-layer detection pipeline in dependency order, for
both symbols, stopping immediately on the first failure:

  feature engineering -> SMC zones (h1) -> CRT (h4) -> liquidity sweeps ->
  volume profile -> divergence (technical, 4 indicators) ->
  inter-market divergence (all models) -> HTF bias

Each stage is invoked as a separate subprocess of the corresponding
individual run_*.py script (unchanged, still independently runnable for
debugging one stage) so a crash in one stage can't leave partial global
state behind for the next. Prints progress per stage and a final pass/fail
summary.

Usage:
    python scripts/detection/run_detection.py
    python scripts/detection/run_detection.py --no-write
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DETECTION = ROOT / "scripts" / "detection"
SYMBOLS = ("XAUUSD", "EURUSD")
DIVERGENCE_INDICATORS = ("rsi", "obv", "stochastic", "cci")


def _cmd(script, *args, no_write=False):
    cmd = [sys.executable, str(DETECTION / script), *args]
    if no_write:
        cmd.append("--no-write")
    return cmd


def build_stages(no_write: bool):
    return [
        ("Feature engineering", [
            _cmd("run_feature_engineering.py", "--symbol", s, no_write=no_write) for s in SYMBOLS
        ]),
        ("SMC zones (h1)", [
            _cmd("run_smc_zone_detection.py", "--symbol", s, "--timeframe", "h1", no_write=no_write) for s in SYMBOLS
        ]),
        ("CRT (h4)", [
            _cmd("run_crt_detection.py", "--symbol", s, "--timeframe", "h4", no_write=no_write) for s in SYMBOLS
        ]),
        ("CRT (h6)", [
            _cmd("run_crt_detection.py", "--symbol", s, "--timeframe", "h6", no_write=no_write) for s in SYMBOLS
        ]),
        ("Liquidity sweeps", [
            _cmd("run_liquidity_sweep_detection.py", "--symbol", s, no_write=no_write) for s in SYMBOLS
        ]),
        ("Volume profile", [
            _cmd("run_volume_profile.py", "--symbol", s, no_write=no_write) for s in SYMBOLS
        ]),
        ("Divergence (technical)", [
            _cmd("run_divergence_detection.py", "--symbol", s, "--indicator", ind, no_write=no_write)
            for s in SYMBOLS for ind in DIVERGENCE_INDICATORS
        ]),
        ("Inter-market divergence", [
            _cmd("run_intermarket_divergence_detection.py", "--model", "all", no_write=no_write)
        ]),
        ("HTF bias", [
            _cmd("run_htf_bias_detection.py", "--symbol", s, no_write=no_write) for s in SYMBOLS
        ]),
    ]


def run_stage(name, commands) -> bool:
    print(f"\n{'=' * 70}\n{name}\n{'=' * 70}")
    for cmd in commands:
        label = f"{Path(cmd[1]).name} {' '.join(cmd[2:])}"
        t0 = time.monotonic()
        result = subprocess.run(cmd, cwd=str(ROOT))
        elapsed = time.monotonic() - t0
        if result.returncode != 0:
            print(f"  [FAIL] {label} (exit {result.returncode}, {elapsed:.1f}s)")
            return False
        print(f"  [OK] {label} ({elapsed:.1f}s)")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="detect and report only, skip DB upserts for every stage")
    args = parser.parse_args()

    stages = build_stages(args.no_write)
    results = []

    for name, commands in stages:
        ok = run_stage(name, commands)
        results.append((name, ok))
        if not ok:
            break

    print(f"\n{'=' * 70}\nDETECTION PIPELINE SUMMARY\n{'=' * 70}")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    ran = len(results)
    total = len(stages)
    if ran < total:
        print(f"\nStopped after {ran}/{total} stages -- {stages[ran][0]} did not run.")

    if not all(ok for _, ok in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
