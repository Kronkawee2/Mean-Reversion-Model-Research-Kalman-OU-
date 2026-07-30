"""
Quantitative Divergence Engine Package.
Unified facade for Data Loading, Feature Engineering, Divergence Detection,
Confirmation Regime Filtering, and Signal Generation.
"""

from .data_collection import DivergenceDataLoader
from .feature_engineering import DivergenceFeatureEngine
from .detection import DivergenceDetector
from .confirmation import DivergenceConfirmationFilter
from .signal_generator import DivergenceSignalGenerator

# Alias for backward compatibility
DivergenceEngine = DivergenceSignalGenerator

__all__ = [
    "DivergenceEngine",
    "DivergenceDataLoader",
    "DivergenceFeatureEngine",
    "DivergenceDetector",
    "DivergenceConfirmationFilter",
    "DivergenceSignalGenerator",
]
