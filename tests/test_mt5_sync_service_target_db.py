"""
Regression test for a real, serious bug: mt5_sync_service.py used to
hardcode GOLD_DB = "raw_gold" as its write target, completely independent
of the SYMBOL variable (driven by MT5_SYMBOL) that controls what actually
gets fetched from MT5. Every sync with MT5_SYMBOL=EURUSD silently wrote
real EURUSD OHLC data into raw_gold (mislabeled as XAUUSD) while
raw_eurusd received nothing -- found via 4 contaminated hours in
raw_gold.h1/m5/m15 (close prices ~1.15-1.16, an impossible range for
gold) traced back to this exact bug.

This project has been bitten by this exact class of bug before (a
hardcoded destination not actually wired to the thing that's supposed to
select it) -- this test is deliberately explicit about the destination-
database mapping, not just "does it run," since that's precisely the
thing that silently broke last time.

Each symbol needs its own fresh process: SYMBOL/RAW_DB/TARGET_DB are
computed once at module-import time from the MT5_SYMBOL env var, so
testing both symbols in one process would only exercise whichever one
imports first (module caching). Subprocess isolation avoids that.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sync" / "scheduler" / "mt5_sync_service.py"

PROBE = (
    "import scripts.sync.scheduler.mt5_sync_service as m; "
    "print(m.SYMBOL, m.TARGET_DB)"
)


def _target_db_for(mt5_symbol: str) -> tuple:
    env = os.environ.copy()
    env["MT5_SYMBOL"] = mt5_symbol
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=str(ROOT), env=env,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"probe failed for {mt5_symbol}: {result.stderr}"
    symbol, target_db = result.stdout.strip().split()
    return symbol, target_db


def test_eurusd_writes_to_raw_eurusd_not_raw_gold():
    print("=" * 60)
    print("1. MT5_SYMBOL=EURUSD must target raw_eurusd, never raw_gold")
    print("=" * 60)

    symbol, target_db = _target_db_for("EURUSD")
    assert symbol == "EURUSD"
    assert target_db == "raw_eurusd", f"EURUSD sync targeted {target_db!r} instead of raw_eurusd -- this is exactly the bug that corrupted raw_gold"

    print(f"  [+] MT5_SYMBOL=EURUSD -> TARGET_DB={target_db}")
    print("  [OK] test_eurusd_writes_to_raw_eurusd_not_raw_gold PASSED\n")


def test_xauusd_writes_to_raw_gold_not_raw_eurusd():
    print("=" * 60)
    print("2. MT5_SYMBOL=XAUUSD must target raw_gold, never raw_eurusd")
    print("=" * 60)

    symbol, target_db = _target_db_for("XAUUSD")
    assert symbol == "XAUUSD"
    assert target_db == "raw_gold", f"XAUUSD sync targeted {target_db!r} instead of raw_gold"

    print(f"  [+] MT5_SYMBOL=XAUUSD -> TARGET_DB={target_db}")
    print("  [OK] test_xauusd_writes_to_raw_gold_not_raw_eurusd PASSED\n")


def test_default_symbol_is_xauusd_targeting_raw_gold():
    print("=" * 60)
    print("3. With MT5_SYMBOL unset, the default (XAUUSD) must still")
    print("   target raw_gold -- confirms the default wasn't broken by")
    print("   making the destination symbol-driven")
    print("=" * 60)

    env = os.environ.copy()
    env.pop("MT5_SYMBOL", None)
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=str(ROOT), env=env,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    symbol, target_db = result.stdout.strip().split()
    assert symbol == "XAUUSD"
    assert target_db == "raw_gold"

    print(f"  [+] MT5_SYMBOL unset -> defaults to {symbol}, TARGET_DB={target_db}")
    print("  [OK] test_default_symbol_is_xauusd_targeting_raw_gold PASSED\n")


def test_unknown_symbol_fails_loudly_instead_of_silently_picking_a_db():
    print("=" * 60)
    print("4. An MT5_SYMBOL with no RAW_DB mapping must fail loudly at")
    print("   import time, not silently fall back to some default db")
    print("=" * 60)

    env = os.environ.copy()
    env["MT5_SYMBOL"] = "GBPUSD"
    result = subprocess.run(
        [sys.executable, "-c", PROBE], cwd=str(ROOT), env=env,
        capture_output=True, text=True,
    )
    assert result.returncode != 0, "an unmapped symbol must raise, not silently succeed"
    assert "GBPUSD" in result.stderr and "RAW_DB" in result.stderr

    print("  [+] raised ValueError mentioning the unmapped symbol and RAW_DB, as expected")
    print("  [OK] test_unknown_symbol_fails_loudly_instead_of_silently_picking_a_db PASSED\n")


def main():
    print("\n" + "#" * 60)
    print("   mt5_sync_service.py — TARGET_DB REGRESSION TESTS")
    print("#" * 60 + "\n")

    test_eurusd_writes_to_raw_eurusd_not_raw_gold()
    test_xauusd_writes_to_raw_gold_not_raw_eurusd()
    test_default_symbol_is_xauusd_targeting_raw_gold()
    test_unknown_symbol_fails_loudly_instead_of_silently_picking_a_db()

    print("#" * 60)
    print("   ALL TESTS PASSED")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    main()
