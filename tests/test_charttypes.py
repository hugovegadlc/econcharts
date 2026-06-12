"""Unit-level coverage of the per-type renderer dispatch."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest

from econcharts import charttypes
from econcharts.charttypes import ChartTypeError, RenderContext


@pytest.fixture
def ax():
    fig, ax = plt.subplots()
    yield ax
    plt.close(fig)


def _xy(n=6):
    return np.arange(float(n)), np.array([1.0, 2.0, 1.5, 3.0, 2.5, 4.0])[:n]


def test_unknown_type_raises(ax):
    x, y = _xy()
    with pytest.raises(ChartTypeError, match="not supported"):
        charttypes.draw(ax, "pie", x, y, "#001391", "L", RenderContext(step=1.0))


def test_line_is_smoothed_to_many_vertices(ax):
    x, y = _xy()
    charttypes.draw(ax, "line", x, y, "#001391", "L", RenderContext(step=1.0))
    assert len(ax.get_lines()[0].get_xdata()) > len(x)


def test_bar_emits_one_patch_per_point(ax):
    x, y = _xy()
    charttypes.draw(ax, "bar", x, y, "#001391", "L", RenderContext(step=1.0))
    assert len(ax.patches) == len(x)


def test_bar_width_scales_with_step(ax):
    x, y = _xy()
    ctx = RenderContext(step=10.0, bar_width_frac=0.8)
    charttypes.draw(ax, "bar", x, y, "#001391", "L", ctx)
    assert ax.patches[0].get_width() == pytest.approx(8.0)
