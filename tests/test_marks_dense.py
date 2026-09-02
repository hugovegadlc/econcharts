"""A label on a DENSE line must clear its own curve.

Every other mark test in this suite uses a chart of a dozen points, where a
label is narrower than the gap between them and its two neighbours are the
whole story. That is why the defect this file pins survived a green suite: it
only appears once the label is wider than the points it spans, which no fixture
here was. The Excel edition found it by rendering an 86-point monthly series
into an 85mm panel and looking at the result.

The assertion is the one a reader would make by eye - does the drawn line pass
through the label's box - measured in display space after layout.
"""
from __future__ import annotations

import math

import matplotlib
import pytest

matplotlib.use("Agg")

from econcharts.render import render          # noqa: E402
from econcharts.spec import Spec              # noqa: E402

N = 86
_PERIODS = [f"{2019 + (m // 12)}M{m % 12 + 1:02d}" for m in range(N)]
# A deterministic series with the shape that matters: spikes and troughs close
# enough together that a label spans several of them.
_VALUES = [3000 + 180 * math.sin(i / 3.1) + 90 * math.sin(i / 1.3) + 60 * math.sin(i / 7.7)
           for i in range(N)]
_MARKS = [_PERIODS[i] for i in (12, 24, 36, 48, 60, 72, N - 1)]


def _dense_spec():
    return Spec(period=f"{_PERIODS[0]}:{_PERIODS[-1]}",
                series=[{"name": "Serie", "type": "line",
                         "data": dict(zip(_PERIODS, _VALUES)),
                         "mark": {"at": _MARKS, "decimals": 0, "marker": True}}])


def _label_boxes_and_line(fig):
    from matplotlib.lines import Line2D
    ax = fig.axes[0]
    renderer = fig.canvas.get_renderer()
    labels = [t for t in ax.texts if t.get_text().strip()]
    curve = max((a for a in ax.lines if len(a.get_xdata()) > 2),
                key=lambda a: len(a.get_xdata()))
    pts = ax.transData.transform(list(zip(curve.get_xdata(), curve.get_ydata())))
    return [(t, t.get_window_extent(renderer)) for t in labels], pts


def test_a_dense_chart_puts_no_label_on_its_own_curve():
    fig = render(_dense_spec(), size="slides_half")
    fig.draw_without_rendering()
    boxes, pts = _label_boxes_and_line(fig)
    assert len(boxes) == len(_MARKS), "fixture no longer marks what it thinks"

    offenders = []
    for text, bb in boxes:
        # The curve is drawn with a stroke of real width; count a hit only when
        # a vertex is properly inside the box, not merely grazing its edge.
        hit = [(x, y) for x, y in pts
               if bb.x0 + 1 <= x <= bb.x1 - 1 and bb.y0 + 1 <= y <= bb.y1 - 1]
        if hit:
            offenders.append(f"{text.get_text()!r} has {len(hit)} curve vertices inside it")
    assert not offenders, "labels sitting on the curve: " + "; ".join(offenders)


def test_the_fixture_is_actually_dense():
    """Guards the test above: if the label ever fits between two points, the
    rule under test is not being exercised at all and the pass would be
    vacuous."""
    fig = render(_dense_spec(), size="slides_half")
    fig.draw_without_rendering()
    renderer = fig.canvas.get_renderer()
    ax = fig.axes[0]
    label = next(t for t in ax.texts if t.get_text().strip())
    width_px = label.get_window_extent(renderer).width
    x0, x1 = ax.transData.transform([(0, 0), (1, 0)])[:, 0]
    per_point_px = abs(x1 - x0)
    assert width_px > 3 * per_point_px, (
        f"label {width_px:.1f}px spans only {width_px / per_point_px:.1f} points")
