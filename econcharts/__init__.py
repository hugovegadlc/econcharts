"""econcharts — publication-quality economic charts from a minimal spec."""

from econcharts.errors import EconchartsError
from econcharts.spec import Spec, Series
from econcharts.render import render, save

__all__ = ["EconchartsError", "Spec", "Series", "render", "save"]
__version__ = "0.1.0"
