"""Per-series data-label marks: value text and (for lines) optional dots.

A mark labels a series' values at chosen points (`at` = all / last / token(s)).
Placement is per chart type:
  line    -> optional dot + value above the point, series color
  bar     -> value on top (below if negative), bar color
  area    -> value just above the curve, series color
  stacked -> value centered in the segment, auto white/navy contrast; render
             hides ones that don't fit (see render._finalize_marks)

Decimals are made consistent across an axis by the caller (`decimals_for`).
Line-label collisions are handled deterministically: `draw_line_marks` picks each
label's side (max above / min below; cross-series ranked; 3+ at the last point go
right), then `render._finalize_marks` offsets above/below labels perpendicular to
the local slope by a constant gap and spreads cramped right labels with leaders.
"""

from __future__ import annotations

import math

from econcharts.data import parse_period
from econcharts.theme import es_pe, label_contrast_color, value_decimals

_Z_MARKER = 4.0
_Z_LABEL = 5.0
_MARKER_SIZE = 5
_LABEL_FONTSIZE = 8

#: gid tagged on every mark artist so render can find them (fit check + limit growth).
MARK_GID = "_econ_mark"


def draw_marks(ax, series, periods, x, y, color, decimals, ctx, geom) -> None:
    """Draw a bar/area/stacked series' marks. (Line marks are placed together by
    `draw_line_marks` so their above/below sides can be chosen across series.)"""
    mark = series.mark
    if mark is None:
        return
    for i in _resolve_points(mark.at, periods):
        if series.type == "bar":
            index, count = geom["group"]
            offset = (index - (count - 1) / 2) * (ctx.step * ctx.bar_width_frac / count)
            _bar_mark(ax, mark, x[i] + offset, y[i], color, decimals)
        elif series.type == "area":
            _area_mark(ax, mark, x[i], geom["top"][i], y[i], color, decimals)
        elif series.type == "stacked":
            _stacked_mark(ax, mark, x[i], geom["bottoms"][i], geom["vals"][i], color, decimals, ctx)


def draw_line_marks(ax, line_series, decimals) -> None:
    """Place all line marks, choosing each label's side by context: at a shared x
    the highest value goes above and the lowest below; for a lone point, a local
    maximum goes above and a local minimum below (labels sit on the outer side)."""
    points = []  # (xi, yi, color, mark, x_array, y_array, idx)
    for series, periods, x, y, color in line_series:
        for i in _resolve_points(series.mark.at, periods):
            points.append((x[i], y[i], color, series.mark, x, y, i))
    groups: dict = {}
    for p in points:
        groups.setdefault(round(p[0], 6), []).append(p)
    last_x = max(groups) if groups else None
    for gx, grp in groups.items():
        grp.sort(key=lambda p: p[1])  # by value, ascending
        # 3+ series labelled at the rightmost point -> right of each endpoint
        # (above/below can't fit them); the x-axis grows to make room.
        right = (gx == last_x and len(grp) >= 3)
        for k, (xi, yi, color, mark, xarr, yarr, i) in enumerate(grp):
            if right:
                side = "right"
            elif len(grp) > 1:
                side = "below" if k == 0 else "above"   # lowest below, rest above
            else:
                side = _single_point_side(yarr, i)
            prev_pt = (xarr[i - 1], yarr[i - 1]) if i > 0 else None
            next_pt = (xarr[i + 1], yarr[i + 1]) if i < len(yarr) - 1 else None
            _draw_one_line_mark(ax, mark, xi, yi, color, decimals, side, prev_pt, next_pt)


def marked_values(series, periods, y) -> list[float]:
    """Values this series will show as NUMERIC labels (for axis decimal sizing)."""
    mark = series.mark
    if mark is None or mark.text is not None or not mark.value:
        return []
    return [y[i] for i in _resolve_points(mark.at, periods)]


def decimals_for(values, cap: int = 2) -> int:
    """The decimal count to use for a set of value labels: the max any one needs."""
    return max((value_decimals(v, cap) for v in values), default=0)


# --- per-type placement ------------------------------------------------------

def _single_point_side(y, i) -> str:
    """A lone point's label side: local max -> above, local min -> below, else above."""
    neighbors = [y[j] for j in (i - 1, i + 1) if 0 <= j < len(y)]
    if not neighbors:
        return "above"
    if y[i] <= min(neighbors):
        return "below"
    return "above"


# Constant gap (points) between a line label's near edge and its data point —
# the same small clearance a label on a flat section has, applied on any slope.
PERP_GAP = 3.0


def perp_unit(ax, xi, yi, prev_pt, next_pt, side):
    """Unit vector perpendicular to the line's local slope (display space), on the
    chosen side. Render scales it by the label's reach + PERP_GAP so the visible
    gap stays constant whatever the slope or label width."""
    p = ax.transData.transform((xi, yi))
    ends = [ax.transData.transform(q) for q in (prev_pt, next_pt) if q is not None]
    if len(ends) == 2:
        tx, ty = ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]
    elif len(ends) == 1:
        tx, ty = ends[0][0] - p[0], ends[0][1] - p[1]
    else:
        tx, ty = 1.0, 0.0
    n = math.hypot(tx, ty) or 1.0
    ox, oy = -ty / n, tx / n                       # unit perpendicular (display)
    if (side == "above") != (oy > 0):              # point it to the chosen side
        ox, oy = -ox, -oy
    return ox, oy


def _draw_one_line_mark(ax, mark, xi, yi, color, decimals, side, prev_pt, next_pt) -> None:
    if mark.marker:
        (dot,) = ax.plot([xi], [yi], marker="o", markersize=_MARKER_SIZE, color=color,
                         linestyle="none", zorder=_Z_MARKER)
        dot.set_gid(MARK_GID)
        dot.set_in_layout(False)
    text = _label_text(mark, yi, decimals)
    if text is not None:
        if side == "right":
            ann = _label(ax, text, (xi, yi), (6, 0), "left", "center", color)
            ann._econ_right = (xi, yi)   # render may spread these + add leaders
        else:
            # offset set in render._finalize_marks (perpendicular to the slope,
            # using the FINAL transform); store what that needs.
            ann = _label(ax, text, (xi, yi), (0, 0), "center", "center", color)
            ann._econ_perp = (xi, yi, prev_pt, next_pt, side)


def _bar_mark(ax, mark, xi, value, color, decimals) -> None:
    text = _label_text(mark, value, decimals)
    if text is None:
        return
    va, dy = ("bottom", 3) if value >= 0 else ("top", -3)  # on top, or below if negative
    _label(ax, text, (xi, value), (0, dy), "center", va, color)


def _area_mark(ax, mark, xi, top_i, value, color, decimals) -> None:
    text = _label_text(mark, value, decimals)
    if text is None:
        return
    _label(ax, text, (xi, top_i), (0, 3), "center", "bottom", color)  # just above the curve


def _stacked_mark(ax, mark, xi, bottom, value, color, decimals, ctx) -> None:
    text = _label_text(mark, value, decimals)
    if text is None or value == 0:
        return
    y0, y1 = sorted((bottom, bottom + value))
    ann = ax.annotate(text, (xi, (y0 + y1) / 2), ha="center", va="center",
                      fontsize=_LABEL_FONTSIZE, color=label_contrast_color(color),
                      zorder=_Z_LABEL)
    ann.set_gid(MARK_GID)
    ann.set_in_layout(False)
    # segment box (data coords) so render can hide the label if it doesn't fit.
    ann._econ_fit = (y0, y1, xi, ctx.step * ctx.bar_width_frac)


# --- helpers -----------------------------------------------------------------

def _resolve_points(at, periods) -> list[int]:
    n = len(periods)
    if at == "all":
        return list(range(n))
    if at == "last":
        return [n - 1] if n else []
    tokens = at if isinstance(at, list) else [at]
    wanted = {parse_period(t) for t in tokens}
    return [i for i, p in enumerate(periods) if p in wanted]


def _label_text(mark, value, decimals: int) -> str | None:
    if mark.text is not None:
        return mark.text          # custom text replaces the value
    if mark.value:
        return es_pe(value, decimals)
    return None


def _label(ax, text, xy, offset, ha, va, color):
    ann = ax.annotate(text, xy, textcoords="offset points", xytext=offset, ha=ha, va=va,
                      fontsize=_LABEL_FONTSIZE, color=color, zorder=_Z_LABEL)
    ann.set_gid(MARK_GID)
    ann.set_in_layout(False)   # marks never resize the axes (constrained layout ignores them)
    return ann
