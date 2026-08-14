"""
Quantitative Smart Money Concepts (SMC) & Candle Range Theory (CRT) Package.
Unified facade for Structure, Liquidity, Imbalance, Order Blocks, CRT Engine, and Scoring Strategy Blueprint.
"""

from .structure import SMCStructureEngine
from .liquidity import SMCLiquidityEngine
from .imbalance import SMCImbalanceEngine
from .order_block import SMCOrderBlockEngine
from .crt_engine import CRTEngine
from .scoring import SMCScoringEngine
from .zone_state import SMCZoneStateEngine
from .crt_state import CRTStateEngine
from .liquidity_state import LiquiditySweepStateEngine

# Compatibility aliases
SMCEngine = SMCScoringEngine

__all__ = [
    "SMCEngine",
    "SMCStructureEngine",
    "SMCLiquidityEngine",
    "SMCImbalanceEngine",
    "SMCOrderBlockEngine",
    "CRTEngine",
    "SMCScoringEngine",
    "SMCZoneStateEngine",
    "CRTStateEngine",
    "LiquiditySweepStateEngine",
]
