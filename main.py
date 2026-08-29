"""
Data-sync entry point:

  1. MT5 sync (gold + eurusd, m5/m15/h1)
  2. Yahoo sync (scripts/sync/sync_yahoo.py -- gold/eurusd h4+d1, macro assets)

The old SMC/Composite Confluence detection pipeline (stage 3) was retired
along with the rest of analysis/smc_crt, analysis/features,
analysis/divergence, analysis/volume_profile, and scripts/detection --
the project pivoted to a Kalman-filter mean-reversion strategy
(analysis/strategies/kalman_mean_reversion.py), which reads raw OHLCV
directly and has no curated-layer detection stage of its own yet. This
script now only keeps the raw data flowing.

Each stage runs as a subprocess of the existing standalone script, stopping
immediately on the first failure. Prints progress per stage and a final
pass/fail summary.

Usage:
    python main.py
"""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MT5_SYNC_SERVICE = ROOT / "scripts" / "sync" / "scheduler" / "mt5_sync_service.py"
SYNC_YAHOO = ROOT / "scripts" / "sync" / "sync_yahoo.py"
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

    print(f"\n{'#' * 70}\nPIPELINE SUMMARY\n{'#' * 70}")
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")

    if not all(ok for _, ok in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
