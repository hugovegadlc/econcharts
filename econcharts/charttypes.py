"""Per-series renderers, dispatched by `Series.type`.

Each renderer draws ONE series onto a shared Axes. All series share an x grid of
matplotlib date numbers (period -> date2num); a `RenderContext` carries the
common geometry (spacing between periods) so bars can size themselves.

Stacking and secondary-axis handling arrive in later chunks; for now each
renderer is independent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator


class ChartTypeError(ValueError):
    """A series asked for a chart type the renderer doesn't support yet."""


@dataclass(frozen=True)
class RenderContext:
    """Geometry shared across a chart's series."""

    step: float                  # median spacing between adjacent periods (date-num units)
    bar_width_frac: float = 0.8  # fraction of a period occupied by its bar slot
    bar_group_gap: float = 0.18  # gap between dodged bars within a group (frac of sub-slot)


# Stroke vocabulary (spec `line:`) -> matplotlib linestyle.
LINESTYLES = {"solid": "-", "dashed": "--", "dotted": ":"}


def draw(ax, kind: str, x, y, color: str, label: str, ctx: RenderContext,
         group: tuple[int, int] = (0, 1), linestyle: str = "-") -> None:
    """Dispatch one series to its renderer.

    `group` = (index, count) of this series among same-type series that share the
    period slot (used by `bar` to dodge side-by-side). Ignored by line/area.
    `linestyle` applies to line series only.
    """
    renderer = _RENDERERS.get(kind)
    if renderer is None:
        supported = ", ".join(sorted(_RENDERERS))
        raise ChartTypeError(f"chart type {kind!r} not supported yet (have: {supported})")
    if kind == "line":
        renderer(ax, x, y, color, label, ctx, group, linestyle)
    else:
        renderer(ax, x, y, color, label, ctx, group)


# Layering by type role: filled backgrounds at the back, lines always in front,
# independent of the order series appear in the spec.
Z_AREA = 1
Z_BAR = 2
Z_LINE = 3


def draw_line(ax, x, y, color, label, ctx, group, linestyle="-") -> None:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    span = _finite_span(y)
    if span is None:
        return  # series is entirely missing — nothing to draw
    lo, hi = span
    # Start at the first real value and end at the last: missing values sit only at
    # the ends (assumed no interior gaps), so the line spans [lo, hi], not the full
    # axis. Smoothing runs on that sub-range so the ends aren't extrapolated.
    xs, ys = _smooth(x[lo:hi + 1], y[lo:hi + 1])
    ax.plot(xs, ys, color=color, label=label, linestyle=linestyle, zorder=Z_LINE)


def draw_area_band(ax, x, base, top, color, label) -> None:
    """Fill a smoothed band between `base` and `top` (a stacked-area layer).

    For a single area, `base` is zeros so it fills curve->0. For stacked areas,
    `base` is the cumulative top of the layers below. Both boundaries are smoothed
    on the SAME fine grid so they never cross. Legend handle is the filled patch.
    """
    xs = _grid(x)
    bases = _smooth_onto(x, base, xs)
    tops = _smooth_onto(x, top, xs)
    # Opaque (areas stack, so they don't overlap) — the grid sits behind them.
    ax.fill_between(xs, bases, tops, facecolor=color, linewidth=0,
                    zorder=Z_AREA, label=label)
    ax.plot(xs, tops, color=color, linewidth=1.2, zorder=Z_AREA + 0.2)


def draw_stacked_bar(ax, x, height, bottom, color, label, ctx) -> None:
    """A full-width bar layer sitting on `bottom` (per-period running baseline).

    Positives stack up from 0, negatives down from 0 — the caller supplies the
    matching baseline so the layer extends in the right direction.
    """
    ax.bar(
        x, height,
        bottom=bottom,
        width=ctx.step * ctx.bar_width_frac,
        align="center",
        color=color,
        label=label,
        zorder=Z_BAR,
    )


def draw_bar(ax, x, y, color, label, ctx, group) -> None:
    """Grouped (dodged) bars: the period's bar slot is split evenly across the
    `count` bar series; this series takes its `index` sub-slot. When grouped, a
    small gap separates adjacent bars (single bars keep the full slot width).
    """
    index, count = group
    subslot = ctx.step * ctx.bar_width_frac / count
    gap = ctx.bar_group_gap if count > 1 else 0.0
    width = subslot * (1 - gap)
    offset = (index - (count - 1) / 2) * subslot
    ax.bar(
        x + offset, y,
        width=width,
        align="center",
        color=color,
        label=label,
        zorder=Z_BAR,
    )


_RENDERERS: dict[str, Callable] = {
    "line": draw_line,
    "bar": draw_bar,
}


def _finite_span(y: np.ndarray) -> tuple[int, int] | None:
    """(first, last) indices of the finite values; None if all are missing.

    Missing values are assumed to occur only at the ends (no interior gaps), so a
    line is drawn from its first real point to its last instead of across the whole
    axis. Interior NaNs, if any slipped in, are still bridged by the smoother.
    """
    finite = np.flatnonzero(np.isfinite(np.asarray(y, dtype=float)))
    if finite.size == 0:
        return None
    return int(finite[0]), int(finite[-1])


def _grid(x_num: np.ndarray, density: int = 40) -> np.ndarray:
    """The fine x grid a smoothed curve is evaluated on (or the raw x if <3 pts)."""
    x_num = np.asarray(x_num, dtype=float)
    if len(x_num) < 3:
        return x_num
    return np.linspace(x_num[0], x_num[-1], max(len(x_num) * density, 200))


def _smooth_onto(x_num: np.ndarray, y: np.ndarray, xs: np.ndarray) -> np.ndarray:
    """Evaluate a monotone-cubic (PCHIP) fit of (x, y) on the grid `xs`.

    PCHIP is C1-smooth and never overshoots, so it won't invent peaks/dips
    between observed points. Falls back to linear if <3 finite values; interior
    NaNs are bridged.
    """
    x_num, y = np.asarray(x_num, dtype=float), np.asarray(y, dtype=float)
    mask = np.isfinite(y)
    if mask.sum() < 3:
        return np.interp(xs, x_num, y)
    return PchipInterpolator(x_num[mask], y[mask])(xs)


def _smooth(x_num: np.ndarray, y: np.ndarray, density: int = 40):
    xs = _grid(x_num, density)
    return xs, _smooth_onto(x_num, y, xs)
