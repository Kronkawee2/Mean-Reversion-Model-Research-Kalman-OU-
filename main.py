"""
Single entry point for the full pipeline, end to end:

  1. MT5 sync (gold + eurusd, m5/m15/h1)
  2. Yahoo sync (scripts/sync/sync_yahoo.py -- gold/eurusd h4+d1, macro assets)
  3. Full detection pipeline (scripts/detection/run_detection.py)

Each stage runs as a subprocess of the existing standalone script, stopping
immediately on the first failure. Prints progress per stage and a final
pass/fail summary.

Usage:
    python main.py
    python main.py --no-write   # detection stages only: report, skip DB upserts
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MT5_SYNC_SERVICE = ROOT / "scripts" / "sync" / "scheduler" / "mt5_sync_service.py"
SYNC_YAHOO = ROOT / "scripts" / "sync" / "sync_yahoo.py"
RUN_DETECTION = ROOT / "scripts" / "detection" / "run_detection.py"
MT5_SYMBOLS = ("XAUUSD", "EURUSD")


def run_step(label, cmd, env=None):
    print(f"\n{'#' * 70}\n{label}\n{'#' * 70}")
    t0 = time.monotonic()
    result = subprocess.run(cmd, cwd=str(ROOT), env=env)
    elapsed = time.monotonic() - t0
    ok = result.returncode == 0
    print(f"{'[OK]' if ok else '[FAIL]'} {label} ({elapsed:.1f}s)")
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="pass through to the detection pipeline: report only, skip DB upserts")
    args = parser.parse_args()

    results = []
    all_ok = True

    for symbol in MT5_SYMBOLS:
        if not all_ok:
            break
        env = os.environ.copy()
        env["MT5_SYMBOL"] = symbol
        ok = run_step(f"MT5 sync -- {symbol} (m5/m15/h1)", [sys.executable, str(MT5_SYNC_SERVICE), "--once"], env=env)
        results.append((f"MT5 sync ({symbol})", ok))
        all_ok = ok

    if all_ok:
        ok = run_step("Yahoo sync (gold/eurusd h4+d1, DXY/US10Y/VIX/GDX)", [sys.executable, str(SYNC_YAHOO)])
        results.append(("Yahoo sync", ok))
        all_ok = ok

    if all_ok:
        detection_cmd = [sys.executable, str(RUN_DETECTION)]
        if args.no_write:
            detection_cmd.append("--no-write")
        ok = run_step("Detection pipeline (features -> SMC -> CRT -> sweeps -> volume profile -> divergence -> HTF bias)", detection_cmd)
        results.append(("Detection pipeline", ok))

    print(f"\n{'#' * 70}\nPIPELINE SUMMARY\n{'#' * 70}")
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")

    if not all(ok for _, ok in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
