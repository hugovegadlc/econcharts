"""The fan type: a central path plus nested uncertainty intervals.

A fan is one line and N fills, and each fill is between TWO curves. That is the
whole idea, and most of what is worth pinning follows from it: the fills must
not stack, the author's ordering must not matter, and an interval that does not
contain the one inside it is a data mistake no reader could see.
"""
from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")

from econcharts.render import render, RenderError        # noqa: E402
from econcharts.spec import Spec, SpecError              # noqa: E402

_P = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]


def _fan(intervals, central=(3.0, 3.0, 3.0, 3.0)):
    return Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, central)),
        "intervals": intervals}])


def _iv(conf, lo, hi):
    return {"conf": conf, "lo": dict(zip(_P, [lo] * 4)), "hi": dict(zip(_P, [hi] * 4))}


def _fill_heights(fig):
    """Vertical extent of each fill, in the order they were drawn."""
    out = []
    for coll in fig.axes[0].collections:
        ys = [v[1] for path in coll.get_paths() for v in path.vertices]
        out.append(max(ys) - min(ys))
    return out


def test_a_fan_is_one_line_and_n_fills():
    fig = render(_fan([_iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5)]), size="slides_half")
    assert len(fig.axes[0].collections) == 2, "one fill per interval"
    # one Line2D, PCHIP-smoothed like any other line series
    assert len(fig.axes[0].lines) == 1, "the central path is still an ordinary line"


def test_intervals_are_drawn_widest_first_whatever_the_spec_order():
    """The author declares confidences, not draw order. Given inside-out, the
    fills must still come out outside-in or the wider one hides the rest."""
    fig = render(_fan([_iv(30, 2.9, 3.1), _iv(90, 2.0, 4.0), _iv(60, 2.5, 3.5)]),
                 size="slides_half")
    heights = _fill_heights(fig)
    assert heights == sorted(heights, reverse=True),         f"fills drawn inner-first and would be hidden: {heights}"


def test_an_interval_that_does_not_contain_the_next_is_refused():
    """A 90% band narrower than the 60% one is a mispointed column. Nothing on
    the chart would show it — the narrower fill simply vanishes underneath."""
    with pytest.raises(RenderError, match="does not contain"):
        render(_fan([_iv(90, 2.9, 3.1), _iv(60, 2.0, 4.0)]), size="slides_half")


def test_lo_above_hi_is_refused():
    with pytest.raises(RenderError, match="swapped"):
        render(_fan([_iv(90, 4.0, 2.0)]), size="slides_half")


def test_a_fan_needs_intervals_and_intervals_need_a_fan():
    with pytest.raises(SpecError, match="at least one entry in `intervals`"):
        Spec.from_dict({"series": [{"name": "I", "type": "fan", "data": [1, 2]}]})
    with pytest.raises(SpecError, match="only for fan series"):
        Spec.from_dict({"series": [{"name": "I", "type": "line", "data": [1, 2],
                                    "intervals": [_iv(90, 1, 3)]}]})


def test_conf_is_a_percentage_not_a_fraction():
    """0.9 is a legal 0.9% interval and is almost certainly meant as 90%, so it
    is refused with a message that says which."""
    with pytest.raises(SpecError, match="percentage, not a fraction"):
        Spec.from_dict({"series": [{"name": "I", "type": "fan", "data": [1, 2],
                                    "intervals": [_iv(0.9, 1, 3)]}]})


def test_the_fan_starts_where_its_intervals_do():
    """No forecast-origin concept: leading nulls leave the fills empty over
    history, which is the whole mechanism."""
    spec = Spec(period=f"{_P[0]}:{_P[-1]}", series=[{
        "name": "I", "type": "fan", "data": dict(zip(_P, [3.0] * 4)),
        "intervals": [{"conf": 90,
                       "lo": dict(zip(_P, [None, None, 2.0, 1.5])),
                       "hi": dict(zip(_P, [None, None, 4.0, 4.5]))}]}])
    fig = render(spec, size="slides_half")
    ax = fig.axes[0]
    fill_x = [v[0] for p in ax.collections[0].get_paths() for v in p.vertices]
    central_x = ax.lines[0].get_xdata()
    assert min(fill_x) > min(central_x),         "the fill must not cover the periods whose bounds are null"
    assert max(fill_x) == pytest.approx(max(central_x), rel=1e-6),         "but it must reach the end of the horizon"
