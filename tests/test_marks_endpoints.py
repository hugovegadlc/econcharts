"""The two halves of the endpoint rule, which are one rule seen from both ends.

At the LAST point a line has only ONE neighbour, so the side the stroke arrives
from is occupied. `draw_line_marks` says "lowest below, the rest above", which is
right until the series in question arrives from the side its own label was given.

Both halves are pinned here because each is invisible to the other: the falling
case moves the UPPER label down, the rising case moves the LOWER label up, and a
suite that only had the first would never notice the second was missing. That is
exactly how it went — the Excel edition shipped the falling half for months.
"""
from __future__ import annotations

import matplotlib
import pytest

matplotlib.use("Agg")

from econcharts.render import render                     # noqa: E402
from econcharts.spec import Spec                         # noqa: E402

_P = [f"2024M{m:02d}" for m in range(1, 13)]


def _two_series(a_vals, b_vals):
    return Spec(period=f"{_P[0]}:{_P[-1]}", series=[
        {"name": "A", "type": "line", "data": dict(zip(_P, a_vals)), "mark": "last"},
        {"name": "B", "type": "line", "data": dict(zip(_P, b_vals)), "mark": "last"},
    ])


def _label_vs_point(fig, text, x_index, y_value):
    """(label centre y, point y) in DISPLAY coords, where y grows upward."""
    ax = fig.axes[0]
    r = fig.canvas.get_renderer()
    lbl = next(t for t in ax.texts if t.get_text().strip() == text)
    bb = lbl.get_window_extent(r)
    curve = max((a for a in ax.lines if len(a.get_xdata()) > 2),
                key=lambda a: len(a.get_xdata()))
    x = curve.get_xdata()[x_index]
    return (bb.y0 + bb.y1) / 2, ax.transData.transform((x, y_value))[1]


def test_the_lower_label_moves_up_when_its_line_rises_into_the_point():
    """B climbs steeply into its final value, so BELOW - where "lowest goes
    below" puts its label - is where its own stroke is."""
    # The proportions are the real chart's (tasa de empleo adecuado): the lower
    # series climbs 54.5 -> 57.2 into 2026 with the upper one at 63.8. Invented
    # numbers made a marginal case - a one-character label is so narrow that its
    # half-width barely reaches back toward the previous point.
    a = [61.5, 61.5, 61.6, 61.4, 61.5, 61.6, 61.5, 61.4, 61.6, 61.5, 61.2, 63.8]
    b = [51.2, 51.5, 51.8, 52.1, 52.5, 53.0, 53.4, 53.8, 54.0, 54.2, 54.5, 57.2]
    fig = render(_two_series(a, b), size="slides_half")
    fig.draw_without_rendering()
    lbl_y, pt_y = _label_vs_point(fig, "57,2", -1, 57.2)
    assert lbl_y > pt_y, "the lower end label should have moved ABOVE its point"


def test_a_gently_rising_line_keeps_its_label_below():
    """The test is geometric, not merely "is it rising" - a gentle climb does
    not reach the label and must not trigger the flip, or every chart moves."""
    a = [61.5, 61.5, 61.6, 61.4, 61.5, 61.6, 61.5, 61.4, 61.6, 61.5, 61.2, 63.8]
    b = [56.2, 56.4, 56.5, 56.6, 56.7, 56.8, 56.9, 57.0, 57.0, 57.1, 57.1, 57.2]
    fig = render(_two_series(a, b), size="slides_half")
    fig.draw_without_rendering()
    lbl_y, pt_y = _label_vs_point(fig, "57,2", -1, 57.2)
    assert lbl_y < pt_y, "a gentle rise must leave the label below its point"
