"""No mark label may sit on another mark label — across every example spec.

The gap this closes is one the suite had for its whole life. Every other check
is about a label and the CURVE, or about structure and counts; the golden images
compare pixels but were stale for months without anyone noticing, and a stale
baseline cannot report a collision anyway. Nothing asked the geometry directly.

The Excel edition added this check first and it found EIGHT overlapping pairs in
its gallery immediately, on charts that had been looked at all day. Python comes
out clean, so this is a hard assertion rather than the budget that edition needs
— and staying at zero is the thing worth defending.
"""
from __future__ import annotations

import matplotlib
import pytest
import yaml

matplotlib.use("Agg")

import matplotlib.pyplot as plt          # noqa: E402

from conftest import EXAMPLES                            # noqa: E402
from econcharts.render import render                     # noqa: E402
from econcharts.spec import Spec                         # noqa: E402

# Every named size, because density is a property of the target: a chart that
# fits at 140mm can collide at 75mm, and the deck uses more than one.
_SIZES = ("word_half", "slides_half", "slides_full")

# A point of slack. Touching edges are not a collision, and neither is rounding.
_SLACK = 1.0


def _single_chart_specs():
    for f in sorted(EXAMPLES.glob("*.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "charts" not in raw:
            yield f


def _overlaps(fig):
    out = []
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        boxes = [(t.get_text(), t.get_window_extent(renderer))
                 for t in ax.texts if t.get_text().strip() and t.get_visible()]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (ta, a), (tb, b) = boxes[i], boxes[j]
                ox = min(a.x1, b.x1) - max(a.x0, b.x0)
                oy = min(a.y1, b.y1) - max(a.y0, b.y0)
                if ox > _SLACK and oy > _SLACK:
                    out.append(f"{ta!r} overlaps {tb!r} by {ox:.1f} x {oy:.1f}px")
    return out


@pytest.mark.parametrize("size", _SIZES)
def test_no_label_sits_on_another(size):
    specs = list(_single_chart_specs())
    assert specs, "expected example specs to collect"

    failures = []
    for f in specs:
        fig = render(Spec.from_yaml(f), size=size)
        fig.draw_without_rendering()
        for hit in _overlaps(fig):
            failures.append(f"{f.stem} @ {size}: {hit}")
        plt.close(fig)

    sep = chr(10) + "  "
    assert not failures, "labels sitting on other labels:" + sep + sep.join(failures)
