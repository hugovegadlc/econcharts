"""econcharts — publication-quality economic charts from a minimal spec."""

from econcharts.spec import Spec, Series
from econcharts.render import render, save

__all__ = ["Spec", "Series", "render", "save"]
__version__ = "0.1.0"
