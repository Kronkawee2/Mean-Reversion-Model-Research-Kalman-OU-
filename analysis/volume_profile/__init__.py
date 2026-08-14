"""
Quantitative Volume Profile Package for XAU/USD & EUR/USD.
Modular components for Histogram Calculation, Statistical Shape Extraction,
Shape Classification (P-shape, b-shape, D-shape), Signals, and Master Pipeline.
"""

from .calculator import VolumeProfileCalculator
from .statistical_features import ProfileStatisticalFeatures
from .classifier import ProfileClassifier
from .signals import ProfileSignalEngine
from .pipeline import VolumeProfilePipeline
from .session_profile import SessionVolumeProfileEngine

# Compatibility alias
VolumeProfileEngine = VolumeProfilePipeline

__all__ = [
    "VolumeProfileEngine",
    "VolumeProfileCalculator",
    "ProfileStatisticalFeatures",
    "ProfileClassifier",
    "ProfileSignalEngine",
    "VolumeProfilePipeline",
    "SessionVolumeProfileEngine",
]
