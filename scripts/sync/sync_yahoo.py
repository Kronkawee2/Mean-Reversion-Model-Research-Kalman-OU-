"""
Runs the full Yahoo Finance sync across all raw databases: gold/eurusd
h4+d1, plus dxy/us10y/vix/gdx per their own scope (dxy h1+d1, the rest
d1-only) -- see quant_backend.py's QuantBackend.sync_all() for the exact
per-asset breakdown. This is main.py's original content, moved here so
main.py can become the single top-level pipeline entry point (MT5 sync ->
this -> full detection pipeline) instead of doing the Yahoo sync alone.

Airflow's DAG (airflow/dags/quant_daily_sync.py) does NOT call this file --
it imports QuantBackend directly and calls sync_all() itself, so it's
unaffected by this move.

Usage: python scripts/sync/sync_yahoo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.sync.quant_backend import QuantBackend  # noqa: E402


def main():
    backend = QuantBackend()
    try:
        backend.sync_all()
    finally:
        backend.close()


if __name__ == "__main__":
    main()
