"""Annotation overlays — non-data markup drawn on a chart.

Chunks A-B: `hline`/`vline` reference lines and `span`/`band` shaded regions.
The form vocabulary (color / weight / line) is resolved to matplotlib kwargs by
the theme, so the spec stays semantic and themes stay swappable. Date->x
conversions are passed in via `AxisCoords` so they stay centralized in render.
Later chunks add recessions/target (registry) and mark callouts.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

import numpy as np

from econcharts.spec import Band, HLine, Span, Spec, VLine
from econcharts.theme import Theme

# Layering: shaded regions sit at the back (above the grid so it reads through
# the transparent fill); hline is a baseline just behind the series; vline and
# labels sit in front so they stay visible across filled areas/bars.
_Z_FILL = 0.8
_Z_HLINE = 0.9
_Z_VLINE = 3.5
_Z_LABEL = 5.0


class AxisCoords(NamedTuple):
    """Period-token -> axis x converters (owned by render, centralized there)."""

    vline: Callable[[str], float]        # vline position (boundary on bars, else midpoint)
    span_start: Callable[[str], float]   # leading edge of a period
    span_end: Callable[[str], float]     # trailing edge of a period


def draw_annotations(ax, spec: Spec, coords: AxisCoords, theme: Theme) -> None:
    """Draw every annotation in the spec onto the primary axes."""
    for ann in spec.annotations:
        if isinstance(ann, HLine):
            kw = theme.annotation_line_kwargs(ann.color, ann.weight, ann.line)
            for y in _as_list(ann.hline):
                ax.axhline(y, zorder=_Z_HLINE, **kw)
        elif isinstance(ann, VLine):
            kw = theme.annotation_line_kwargs(ann.color, ann.weight, ann.line)
            for token in _as_list(ann.vline):
                ax.axvline(coords.vline(token), zorder=_Z_VLINE, **kw)
        elif isinstance(ann, Span):
            x0, x1 = coords.span_start(ann.span.start), coords.span_end(ann.span.to)
            ax.axvspan(x0, x1, zorder=_Z_FILL, **theme.annotation_fill_kwargs(ann.color))
            if ann.span.label:
                ax.text((x0 + x1) / 2, 0.98, ann.span.label,
                        transform=ax.get_xaxis_transform(), ha="center", va="top",
                        fontsize=8, color=theme.annotation_label_color(ann.color), zorder=_Z_LABEL)
        elif isinstance(ann, Band):
            y0b, y1b = ann.band.y0, ann.band.y1
            ax.axhspan(y0b, y1b, zorder=_Z_FILL, **theme.annotation_fill_kwargs(ann.color))
            if ann.band.label:
                _place_band_label(ax, y0b, y1b, ann.band.label,
                                  theme.annotation_label_color(ann.color))


def _place_band_label(ax, y0, y1, label, color) -> None:
    """Put a band's label in the widest x-stretch where no series enters the band;
    fall back to the top-right corner if the band is crossed everywhere."""
    gx = _band_clear_x(ax, y0, y1)
    if gx is None:
        ax.text(0.99, max(y0, y1), label, transform=ax.get_yaxis_transform(),
                ha="right", va="top", fontsize=8, color=color, zorder=_Z_LABEL)
    else:
        ax.text(gx, (y0 + y1) / 2, label, ha="center", va="center",
                fontsize=8, color=color, zorder=_Z_LABEL)


def _band_clear_x(ax, y0, y1):
    """x at the centre of the widest stretch where no series curve is inside the
    band [y0, y1]; None if no stretch is wide enough (band crossed everywhere)."""
    curves = [l for l in ax.get_lines() if len(l.get_xdata()) > 2]
    if not curves:
        return None
    lo, hi = min(y0, y1), max(y0, y1)
    x0, x1 = sorted(ax.get_xlim())
    grid = np.linspace(x0, x1, 200)
    occupied = np.zeros(grid.size, dtype=bool)
    for line in curves:
        yi = np.interp(grid, np.asarray(line.get_xdata()), np.asarray(line.get_ydata()),
                       left=np.nan, right=np.nan)
        occupied |= (yi >= lo) & (yi <= hi)
    best_len, best_center, i, n = 0, None, 0, grid.size
    while i < n:
        if occupied[i]:
            i += 1
            continue
        j = i
        while j < n and not occupied[j]:
            j += 1
        if j - i > best_len:
            best_len, best_center = j - i, grid[(i + j - 1) // 2]
        i = j
    return best_center if best_center is not None and best_len >= 0.15 * n else None


def _as_list(v):
    return v if isinstance(v, list) else [v]
