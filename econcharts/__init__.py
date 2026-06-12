"""econcharts — publication-quality economic charts from a minimal spec."""

from importlib.metadata import version

from econcharts.errors import EconchartsError
from econcharts.spec import Spec, Series, SpecError
from econcharts.data import DataError
from econcharts.theme import ThemeError
from econcharts.render import render, save, RenderError
from econcharts.batch import BatchError

__version__ = version("econcharts")

__all__ = [
    "EconchartsError", "SpecError", "DataError", "ThemeError", "RenderError", "BatchError",
    "Spec", "Series", "render", "save",
]
