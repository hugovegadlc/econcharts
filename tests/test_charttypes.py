"""Unit-level coverage of the per-type renderers and the CHART_TYPES dispatch."""

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


def test_unknown_type_raises():
    with pytest.raises(ChartTypeError, match="not supported"):
        charttypes.chart_type("pie")


def test_registry_covers_every_spec_type():
    from typing import get_args

    from econcharts.spec import SeriesType

    assert set(charttypes.CHART_TYPES) == set(get_args(SeriesType))


def test_line_is_smoothed_to_many_vertices(ax):
    x, y = _xy()
    charttypes.draw_line(ax, x, y, "#001391", "L", RenderContext(step=1.0), (0, 1))
    assert len(ax.get_lines()[0].get_xdata()) > len(x)


def test_bar_emits_one_patch_per_point(ax):
    x, y = _xy()
    charttypes.draw_bar(ax, x, y, "#001391", "L", RenderContext(step=1.0), (0, 1))
    assert len(ax.patches) == len(x)


def test_bar_width_scales_with_step(ax):
    x, y = _xy()
    ctx = RenderContext(step=10.0, bar_width_frac=0.8)
    charttypes.draw_bar(ax, x, y, "#001391", "L", ctx, (0, 1))
    assert ax.patches[0].get_width() == pytest.approx(8.0)


def test_stacked_layers_accumulate_by_sign(ax):
    """Each stacked layer sits on the running total of its sign: positives stack
    up from 0, negatives down — the GroupState carries that across series."""
    from econcharts.spec import Series

    ctx = RenderContext(step=1.0)
    state = charttypes.GroupState()
    stacked = charttypes.chart_type("stacked")
    s1 = Series(name="a", data=[0], type="stacked")
    s2 = Series(name="b", data=[0], type="stacked")
    x = np.array([0.0, 1.0])
    periods = ["p1", "p2"]  # any hashable keys the accumulators can track

    g1 = stacked.draw(ax, s1, x, np.array([1.0, -1.0]), periods, "#001391", ctx, state, None)
    g2 = stacked.draw(ax, s2, x, np.array([2.0, -2.0]), periods, "#85C8FF", ctx, state, None)

    assert list(g1.bottoms) == [0.0, 0.0]
    assert list(g2.bottoms) == [1.0, -1.0]  # second layer sits on the first, per sign


def test_dodged_bars_take_consecutive_slots(ax):
    """Bars claim dodge slots in spec order via GroupState.bar_seen."""
    from econcharts.spec import Series

    ctx = RenderContext(step=1.0)
    state = charttypes.GroupState(bar_count=2)
    bar = charttypes.chart_type("bar")
    x, y = np.array([0.0, 1.0]), np.array([1.0, 2.0])

    g1 = bar.draw(ax, Series(name="a", data=[0], type="bar"), x, y, [], "#001391", ctx, state, None)
    g2 = bar.draw(ax, Series(name="b", data=[0], type="bar"), x, y, [], "#85C8FF", ctx, state, None)

    assert (g1.index, g1.count) == (0, 2)
    assert (g2.index, g2.count) == (1, 2)
