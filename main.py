"""
Main entry point for Quant Trader Data Engine.
Runs full multi-timeframe sync across all Bronze databases (gold, eurusd, dxy, us10y, vix, gdx).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from quant_backend import QuantBackend


def main():
    backend = QuantBackend()
    try:
        backend.sync_all()
    finally:
        backend.close()


if __name__ == "__main__":
    main()
