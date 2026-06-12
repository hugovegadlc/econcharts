"""econcharts — publication-quality economic charts from a minimal spec."""

from econcharts.errors import EconchartsError
from econcharts.spec import Spec, Series, SpecError
from econcharts.data import DataError
from econcharts.theme import ThemeError
from econcharts.render import render, save, RenderError
from econcharts.batch import BatchError

__all__ = [
    "EconchartsError", "SpecError", "DataError", "ThemeError", "RenderError", "BatchError",
    "Spec", "Series", "render", "save",
]
__version__ = "0.1.0"
