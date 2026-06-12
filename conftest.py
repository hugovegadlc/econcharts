"""Shared test fixtures and a headless matplotlib backend.

Sits at the repo root so `econcharts` is importable when pytest runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display in tests

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXAMPLES = ROOT / "examples"

# The example specs reference examples/datos.xlsx via excel: refs, so point the
# resolver's DATA_ROOT at examples/ for the test session (the intended config
# mechanism). Tests that need a different root pass data_root= or monkeypatch.
os.environ["ECONCHARTS_DATA_ROOT"] = str(EXAMPLES)


@pytest.fixture
def example_spec():
    """The canonical hand-written line spec (two smoothed series, es-PE)."""
    from econcharts import Spec

    return Spec.from_yaml(EXAMPLES / "inflacion_pe.yaml")


@pytest.fixture(autouse=True)
def _close_figures():
    """Close any figures a test opened via render() (caller owns the Figure)."""
    yield
    import matplotlib.pyplot as plt

    plt.close("all")
