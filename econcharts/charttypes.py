"""Per-series chart types: drawing primitives + the strategy classes binding them
to spec series.

`CHART_TYPES` maps a spec `type` to its ChartType singleton — the ONE dispatch
point for everything type-specific: how a series draws (including stacking and
bar dodging, via the shared `GroupState`) and how its value marks place (using
the placement primitives in `marks`). render walks series in spec order and
defers to these classes; adding a chart type (e.g. `fan`) is one new class here,
not parallel switches across modules.

All series share an x grid of matplotlib date numbers (period -> date2num); a
`RenderContext` carries the common geometry (spacing between periods) so bars
can size themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

import numpy as np
from scipy.interpolate import PchipInterpolator

from econcharts import marks
from econcharts.errors import EconchartsError


class ChartTypeError(EconchartsError):
    """A series asked for a chart type the renderer doesn't support yet."""


@dataclass(frozen=True)
class RenderContext:
    """Geometry shared across a chart's series."""

    step: float                  # median spacing between adjacent periods (date-num units)
    bar_width_frac: float = 0.8  # fraction of a period occupied by its bar slot
    bar_group_gap: float = 0.18  # gap between dodged bars within a group (frac of sub-slot)


@dataclass
class GroupState:
    """Mutable cross-series accumulators for one axis group.

    Bars need their dodge slot among the group's bars; each area/stacked layer
    stacks on the running totals left by the layers drawn before it.
    """

    bar_count: int = 0           # bars in this group (known up front)
    bar_seen: int = 0            # bars drawn so far -> the next bar's dodge slot
    area_cum: dict = field(default_factory=dict)   # period -> cumulative area top
    pos_cum: dict = field(default_factory=dict)    # period -> stacked +ve running top
    neg_cum: dict = field(default_factory=dict)    # period -> stacked -ve running bottom


# Per-type geometry captured at draw time, consumed by mark placement.
@dataclass(frozen=True)
class BarGeom:
    index: int                   # this bar's dodge slot among the group's bars
    count: int
    colors: tuple[str, ...] | None = None  # per-bar colors when some bars are highlighted


@dataclass(frozen=True)
class AreaGeom:
    top: np.ndarray              # the layer's upper boundary (base + values)


@dataclass(frozen=True)
class StackedGeom:
    bottoms: np.ndarray          # per-point baseline the layer sits on
    vals: np.ndarray             # per-point heights (NaN coerced to 0)


Geom = Optional[Union[BarGeom, AreaGeom, StackedGeom]]

# Stroke vocabulary (spec `line:`) -> matplotlib linestyle.
LINESTYLES = {"solid": "-", "dashed": "--", "dotted": ":"}

# Layering by type role: filled backgrounds at the back, lines always in front,
# independent of the order series appear in the spec.
Z_AREA = 1
Z_BAR = 2
Z_LINE = 3


# --- strategy classes ----------------------------------------------------------

class ChartType:
    """How one spec `type` draws and labels itself.

    Stateless singletons — all cross-series state lives in the GroupState that
    render passes to `draw`, and per-series geometry travels in the returned Geom.
    """

    #: Line marks are placed across series (side selection needs every line at
    #: once), so LineType defers them to `marks.draw_line_marks` at group level.
    defer_marks = False

    def draw(self, ax, series, x, y, periods, color: str, ctx: RenderContext,
             state: GroupState, theme) -> Geom:
        raise NotImplementedError

    def place_marks(self, ax, series, periods, x, y, color: str, decimals: int,
                    ctx: RenderContext, geom: Geom, theme,
                    placed: list[marks.PlacedMark]) -> None:
        for i in marks.mark_indices(series, periods):
            self._mark_one(ax, series.mark, i, x, y, geom, color, decimals, ctx, theme, placed)

    def _mark_one(self, ax, mark, i, x, y, geom, color, decimals, ctx, theme, placed) -> None:
        raise NotImplementedError


class LineType(ChartType):
    defer_marks = True   # placed cross-series by marks.draw_line_marks

    def draw(self, ax, series, x, y, periods, color, ctx, state, theme) -> Geom:
        draw_line(ax, x, y, color, series.legend_label, ctx, (0, 1),
                  LINESTYLES[series.line])
        return None


class BarType(ChartType):
    def draw(self, ax, series, x, y, periods, color, ctx, state, theme) -> BarGeom:
        colors = _highlight_colors(series, periods, color, theme)
        geom = BarGeom(index=state.bar_seen, count=state.bar_count, colors=colors)
        state.bar_seen += 1
        draw_bar(ax, x, y, colors or color, series.legend_label, ctx,
                 (geom.index, geom.count))
        return geom

    def _mark_one(self, ax, mark, i, x, y, geom, color, decimals, ctx, theme, placed):
        # the label sits over the dodged bar, not the period centre
        offset = (geom.index - (geom.count - 1) / 2) * (ctx.step * ctx.bar_width_frac / geom.count)
        c = geom.colors[i] if geom.colors else color   # label matches its bar
        marks.bar_mark(ax, mark, x[i] + offset, y[i], c, decimals, placed)


class AreaType(ChartType):
    def draw(self, ax, series, x, y, periods, color, ctx, state, theme) -> AreaGeom:
        base = np.array([state.area_cum.get(p, 0.0) for p in periods])
        top = base + y
        draw_area_band(ax, x, base, top, color, series.legend_label)
        state.area_cum.update(dict(zip(periods, top)))   # next area stacks on top
        return AreaGeom(top=top)

    def _mark_one(self, ax, mark, i, x, y, geom, color, decimals, ctx, theme, placed):
        marks.area_mark(ax, mark, x[i], geom.top[i], y[i], color, decimals, placed)


class StackedType(ChartType):
    def draw(self, ax, series, x, y, periods, color, ctx, state, theme) -> StackedGeom:
        vals = np.where(np.isfinite(y), y, 0.0)
        bottoms = np.array([(state.pos_cum if v >= 0 else state.neg_cum).get(p, 0.0)
                            for p, v in zip(periods, vals)])
        draw_stacked_bar(ax, x, vals, bottoms, color, series.legend_label, ctx)
        for p, v, b in zip(periods, vals, bottoms):   # +ve up, -ve down
            (state.pos_cum if v >= 0 else state.neg_cum)[p] = b + v
        return StackedGeom(bottoms=bottoms, vals=vals)

    def _mark_one(self, ax, mark, i, x, y, geom, color, decimals, ctx, theme, placed):
        marks.stacked_mark(ax, mark, x[i], geom.bottoms[i], geom.vals[i],
                           color, decimals, ctx, theme, placed)


CHART_TYPES: dict[str, ChartType] = {
    "line": LineType(),
    "bar": BarType(),
    "area": AreaType(),
    "stacked": StackedType(),
}


def chart_type(kind: str) -> ChartType:
    """The ChartType for a spec `type`, with a clear error for unknown kinds."""
    try:
        return CHART_TYPES[kind]
    except KeyError:
        supported = ", ".join(sorted(CHART_TYPES))
        raise ChartTypeError(
            f"chart type {kind!r} not supported yet (have: {supported})"
        ) from None


def _highlight_colors(series, periods, base: str, theme) -> tuple[str, ...] | None:
    """Per-bar colors when the series highlights some periods (else None).

    The highlighted periods take the spec's named color (or the theme's own
    `highlight` color); the rest keep the series color. `at` resolution shares
    the mark grammar, including the no-match warning."""
    h = series.highlight
    if h is None:
        return None
    accent = theme.resolve_color(h.color) if h.color else theme.highlight_color()
    out = [base] * len(periods)
    for i in marks.at_indices(h.at, periods,
                              owner=f"series {series.name!r}", field="highlight.at"):
        out[i] = accent
    return tuple(out)


# --- drawing primitives ----------------------------------------------------------

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
    `color` is one color, or a per-bar sequence when some bars are highlighted.
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
