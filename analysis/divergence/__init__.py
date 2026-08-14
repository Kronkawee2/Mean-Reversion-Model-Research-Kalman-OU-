"""
Quantitative Divergence Engine Package.
Unified facade for Data Loading, Feature Engineering, Divergence Detection,
Confirmation Regime Filtering, and Signal Generation.
"""

from .data_collection import DivergenceDataLoader
from .feature_engineering import DivergenceFeatureEngine
from .detection import DivergenceDetector, find_price_pivots
from .confirmation import DivergenceConfirmationFilter
from .signal_generator import DivergenceSignalGenerator
from .technical_divergence_state import TechnicalDivergenceEngine
from .intermarket_divergence_state import IntermarketDivergenceEngine, INTERMARKET_MODELS

# Alias for backward compatibility
DivergenceEngine = DivergenceSignalGenerator

__all__ = [
    "DivergenceEngine",
    "DivergenceDataLoader",
    "DivergenceFeatureEngine",
    "DivergenceDetector",
    "find_price_pivots",
    "DivergenceConfirmationFilter",
    "DivergenceSignalGenerator",
    "TechnicalDivergenceEngine",
    "IntermarketDivergenceEngine",
    "INTERMARKET_MODELS",
]
