"""Per-series data-label marks: value text and (for lines) optional dots.

A mark labels a series' values at chosen points (`at` = all / last / token(s)).
This module holds the placement PRIMITIVES; per-type dispatch lives on the
strategy classes in `charttypes.CHART_TYPES`. Placement per chart type:
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

Placement appends a `PlacedMark` record per artist to the list render passes in —
the explicit contract `render._finalize_marks` consumes for its post-layout pass.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, replace

from econcharts.data import parse_period
from econcharts.theme import value_decimals

_Z_MARKER = 4.0
_Z_LABEL = 5.0
_LABEL_FONTSIZE = 8


@dataclass(frozen=True)
class SegmentFit:
    """A stacked label's segment box (data coords) — render hides the label if
    the rendered text doesn't fit the segment's height or the bar's width."""

    y0: float
    y1: float
    xc: float      # segment centre x
    bar_w: float   # bar width (data coords)


@dataclass(frozen=True)
class PerpSpec:
    """What render needs to offset a line label perpendicular to the line's
    local slope at (xi, yi), on the chosen side (see `perp_unit`)."""

    xi: float
    yi: float
    prev_pt: tuple | None
    next_pt: tuple | None
    side: str      # "above" | "below"
    # The whole series, for `clear_lone_marks`: on a dense chart a label is
    # wider than the gap between points, so its two neighbours no longer
    # describe what it has to clear.
    xs: tuple = ()
    ys: tuple = ()


@dataclass
class PlacedMark:
    """One placed mark artist + what render's post-layout pass needs to know.

    The explicit contract between mark placement and `render._finalize_marks`:
    placement appends one record per artist; finalize iterates the list. Every
    record participates in axis-limit growth; the optional fields request the
    per-kind adjustments."""

    artist: object                       # matplotlib Text / Line2D
    fit: SegmentFit | None = None        # stacked: hide if it doesn't fit
    perp: PerpSpec | None = None         # line: slope-perpendicular offset
    right_anchor: tuple | None = None    # (xi, yi): right-of-endpoint spreading


def at_indices(at, periods, *, owner: str, field: str) -> list[int]:
    """The indices an `at` token set points to, warning when an explicit token
    matches nothing — a typo or a date outside the window would otherwise vanish
    silently. (`all`/`last` are exempt: they legitimately resolve empty on an
    empty series.)"""
    indices = _resolve_points(at, periods)
    if not indices and at not in ("all", "last"):
        warnings.warn(
            f"{owner}: {field} {at!r} matched no periods (outside the window or wrong token?)",
            UserWarning, stacklevel=2,
        )
    return indices


def mark_indices(series, periods) -> list[int]:
    """The indices a series' mark points to (the `at` grammar, see `at_indices`)."""
    return at_indices(series.mark.at, periods,
                      owner=f"series {series.name!r}", field="mark.at")


def draw_line_marks(ax, line_series, decimals, placed: list[PlacedMark], theme) -> None:
    """Place all line marks, choosing each label's side by context: at a shared x
    the highest value goes above and the lowest below; for a lone point, a local
    maximum goes above and a local minimum below (labels sit on the outer side)."""
    points = []  # (xi, yi, color, mark, x_array, y_array, idx)
    for series, periods, x, y, color in line_series:
        for i in mark_indices(series, periods):
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
            _draw_one_line_mark(ax, mark, xi, yi, color, decimals, side, prev_pt, next_pt,
                                placed, theme, xarr, yarr)


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


# `format.marks.perp_gap` is the clearance between a line label's near edge and
# its data point, the same on any slope. It lives in the theme because it is a
# preference, and under that name because the Excel edition names it that too.


def spread_pitch(theme, dpi72: float, label_h_px: float) -> float:
    """Minimum centre-to-centre spacing between two separated labels, in px.

    Two parts, and they belong in different places. The label's own HEIGHT is
    the floor: two labels closer than one line of text overlap, which is not a
    style choice and so is not a theme key. The air on top of it is
    `format.marks.spread_gap`, which IS a preference — a denser house sets it
    lower.

    This used to be one multiplier of 1.2, which conflated the two: the 1.0
    nobody may change with the 0.2 anybody may.
    """
    return label_h_px + float(theme.val("format.marks.spread_gap", 1.0)) * dpi72



def separate(want: list[float], pitch: float) -> list[float]:
    """Least-squares isotonic fit: the closest set of positions to `want` that
    keeps `pitch` between neighbours. Pool-adjacent-violators, O(n).

    `want` is ordered top-first in a coordinate that INCREASES downward, and the
    result satisfies ``got[i+1] - got[i] >= pitch``.

    What matters is that it moves ONLY what is crowded. Re-spacing the whole set
    evenly about its common centre — the obvious approach, and what this
    replaced — drags labels that were never crowded: measured on three endpoints
    at 21.5 / 2.9 / 1.8, where only the last two collide, it moved the 21.5
    label 65pt to solve someone else's problem. Here each pooled run is centred
    on its own mean and everything else stays exactly where it wanted to be.
    """
    blocks: list[list[float]] = []          # [value, count] per pooled run
    for i, w in enumerate(want):
        blocks.append([w - i * pitch, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, c2 = blocks.pop()
            v1, c1 = blocks[-1]
            blocks[-1] = [(v1 * c1 + v2 * c2) / (c1 + c2), c1 + c2]
    got: list[float] = []
    for v, c in blocks:
        for _ in range(c):
            got.append(v + len(got) * pitch)
    return got


def flip_end_label_onto_clear_side(ax, placed: list["PlacedMark"], renderer, theme) -> bool:
    """At the LAST point a line has only ONE neighbour, so "above" and "below"
    are not interchangeable the way `_single_point_side` treats an interior
    point: the incoming stroke occupies the side it descends from. A series that
    drops steeply into its final value therefore gets its label placed on its
    own curve.

    `draw_line_marks` says "lowest below, the rest above" at a shared x, which is
    right everywhere except here. With exactly two marks at the last point, the
    upper one drops below its own point instead — into the clear space between
    the two series.

    The test is geometric, not merely "is it falling": what matters is how far
    the stroke rises across the label's own half-width, since the label is
    centred on the point.

        intrusion = fall * min(1, halfLabelWidth / distance to the neighbour)

    Falling alone is a false positive on most charts — measured on the four in
    the Excel edition's decks with exactly two end marks, the one that needed the
    flip intrudes 13.5pt into a 12.5pt label while two others that merely fall
    intrude 1.35pt and 0.76pt.

    The flip is refused when the two endpoints are closer than a label pitch:
    landing on the other label is worse than the collision being avoided.

    Returns True if it moved something (so the caller re-measures).
    """
    ends = [pm for pm in placed if pm.perp is not None and pm.perp.prev_pt is not None]
    if not ends:
        return False
    last_x = max(round(pm.perp.xi, 6) for pm in ends)
    grp = [pm for pm in ends if round(pm.perp.xi, 6) == last_x]
    if len(grp) != 2:
        return False
    upper = next((pm for pm in grp if pm.perp.side == "above"), None)
    lower = next((pm for pm in grp if pm.perp.side == "below"), None)
    if upper is None or lower is None:
        return False
    # A padded `period` frame can leave the neighbour blank; without a real one
    # there is nothing to measure, so leave the label where it is.
    if not all(math.isfinite(float(v)) for v in upper.perp.prev_pt):
        return False

    to_px = ax.transData.transform
    ux, uy = to_px((upper.perp.xi, upper.perp.yi))
    _, ly = to_px((lower.perp.xi, lower.perp.yi))
    prev_x, prev_y = to_px(upper.perp.prev_pt)

    fall = prev_y - uy                       # display y grows upward
    reach = ux - prev_x
    if fall <= 0 or reach <= 0:
        return False                         # rises into the point, or no room to measure
    bb = upper.artist.get_window_extent(renderer)
    intrusion = fall * min(1.0, (bb.width / 2) / reach)
    if intrusion < bb.height / 2:
        return False                         # the stroke never reaches the label
    if abs(uy - ly) < spread_pitch(theme, ax.figure.dpi / 72.0, bb.height):
        return False                         # no room between the two endpoints
    # PerpSpec is frozen; PlacedMark is not, so swap in a new spec.
    upper.perp = replace(upper.perp, side="below")
    return True


def clear_lone_marks(ax, placed: list["PlacedMark"], renderer, theme) -> bool:
    """Give a LONE mark's label the side and the clearance its own width asks
    for, rather than the ones its two neighbours ask for.

    `_single_point_side` looks at the points either side, and on most charts
    that is the whole question: a label narrower than the gap between points
    has nothing else within reach. It stops being the question when the chart
    is dense. Measured on the Excel edition's reconstruction deck, an 86-point
    monthly series in an 85mm panel gives ~2.3pt per category against a ~28pt
    label — twelve points wide, so the label clears six on each side while the
    rule looked at one.

    The failures all had that shape: one series chose "above" for a point whose
    previous neighbour was TWO units lower, while the curve climbed FIFTY-SEVEN
    across the label's own width, and the line ran through the digits. The
    labels that came out clean were the local maxima, which genuinely had
    nothing above them — so the rule was not wrong, its window was.

    Two things follow, and this does both:

    * the side is the one the curve intrudes into less, over the label's width;
    * the offset clears the furthest the curve reaches within that width, not a
      fixed gap from the point — otherwise the right side still grazes it.

    The density gate needs no constant. If no other point falls inside the
    label's own width, the window holds nothing to weigh and the existing
    answer stands, which is exactly the sparse case. So no chart that was
    already right can move.

    Shared-x points are left alone: they have their own rule, and the last
    point of a two-series chart has `flip_end_label_onto_clear_side`. A lone
    mark is left over precisely where no other rule applies — including at the
    last point, where nothing else claims it.

    Placing the label here retires its PerpSpec, so the perpendicular pass
    downstream leaves it alone.

    Returns True if it moved something (so the caller re-measures).
    """
    lone = [pm for pm in placed if pm.perp is not None and pm.perp.xs]
    if not lone:
        return False
    counts: dict = {}
    for pm in lone:
        counts[round(pm.perp.xi, 6)] = counts.get(round(pm.perp.xi, 6), 0) + 1

    to_px = ax.transData.transform
    inv = ax.transData.inverted()
    dpi72 = ax.figure.dpi / 72.0
    gap = float(theme.val("format.marks.perp_gap", 3.0))
    moved = False

    for pm in lone:
        if counts[round(pm.perp.xi, 6)] != 1:
            continue
        spec = pm.perp
        bb = pm.artist.get_window_extent(renderer)      # centred on the point, unoffset
        (xl, _), (xr, _) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y0)])
        half = abs(xr - xl) / 2.0

        win = [y for x, y in zip(spec.xs, spec.ys)
               if abs(float(x) - spec.xi) <= half and math.isfinite(float(y))]
        if len(win) < 2:
            continue                # nothing else under the label: sparse, leave it
        hi, lo = max(win), min(win)
        below = (spec.yi - lo) < (hi - spec.yi)         # ties keep "above"
        y_ex = lo if below else hi

        # Clear the curve's own excursion, measured in display space so the
        # gap is constant on the page whatever the axis scale.
        dy = (to_px((spec.xi, y_ex))[1] - to_px((spec.xi, spec.yi))[1]) / dpi72
        half_h = (bb.height / 2) / dpi72
        pm.artist.xyann = (0, dy + (gap + half_h) * (-1 if below else 1))
        pm.perp = None                                   # placed; skip the perp pass
        moved = True
    return moved


def decollide_across_axes(ax, placed: list["PlacedMark"],
                          ax2, placed2: list["PlacedMark"], theme) -> bool:
    """Separate end-point labels that belong to DIFFERENT value axes.

    Each axis group is drawn and finalized on its own — its own `placed` list,
    its own side rules, its own spread — which is right within a group and blind
    across them. Two labels then land wherever their own axis put them, and on a
    dual-axis chart those can be the same place: measured on the *Dolarización*
    shape, the primary's 40,4 and the secondary's 6,6 came out in an identical
    y band, 228.7..238.7, overlapping outright.

    Nothing is moved unless two labels actually overlap, so a single-axis chart
    and a well-spaced dual-axis one are untouched. When they do, the whole
    last-point set is separated isotonically about where it already is, in
    display space — the one coordinate system the two axes share.
    """
    if ax2 is None:
        return False
    items = []                      # (artist, anchor_display_x)
    for a, group in ((ax, placed), (ax2, placed2)):
        for pm in group:
            anchor_pt = pm.right_anchor or (pm.perp and (pm.perp.xi, pm.perp.yi))
            if anchor_pt is None:
                continue
            items.append((pm.artist, a.transData.transform(anchor_pt)[0]))
    if len(items) < 2:
        return False
    last_x = max(x for _, x in items)
    group = [artist for artist, x in items if abs(x - last_x) < 1.0]
    if len(group) < 2:
        return False

    fig = ax.figure
    fig.draw_without_rendering()
    renderer = fig.canvas.get_renderer()
    boxes = [(a, a.get_window_extent(renderer)) for a in group]
    if not any(b1.overlaps(b2) for i, (_, b1) in enumerate(boxes)
               for _, b2 in boxes[i + 1:]):
        return False

    boxes.sort(key=lambda t: -(t[1].y0 + t[1].y1) / 2)          # top first
    pitch = spread_pitch(theme, fig.dpi / 72.0, max(bb.height for _, bb in boxes))
    centres = [(bb.y0 + bb.y1) / 2 for _, bb in boxes]
    targets = [-v for v in separate([-c for c in centres], pitch)]

    dpi72 = fig.dpi / 72.0
    for (artist, _bb), centre, target in zip(boxes, centres, targets):
        if abs(target - centre) < 0.5:
            continue
        dx, dy = artist.xyann
        artist.xyann = (dx, dy + (target - centre) / dpi72)
    return True


# Minimum horizontal component of the perpendicular vector before the
# slope-aware offset is applied. Below this (~17° slope) the perpendicular
# is nearly vertical and the label cannot meaningfully overlap the line.
PERP_SLOPE_THRESHOLD = 0.3


def perp_unit(ax, spec: PerpSpec):
    """Perpendicular unit vector (display space) on the chosen side, plus
    an extremum flag.

    Returns (ox, oy, extremum):
      ox, oy    — unit vector perpendicular to the local slope, pointing to `side`.
      extremum  — True when the slopes on either side have opposite signs (local min
                  or max), or at an endpoint. Render uses a plain vertical offset at
                  extrema and on shallow slopes; the perpendicular is only applied on
                  steep monotone sections where a vertical label could overlap the line.

    On steep monotone sections the tangent is chosen by curvature: rising lines use
    the incoming slope (m0), falling lines use the outgoing slope (m1). This encodes
    the curvature rule (sign of slope × Δslope) as a single perpendicular direction
    rather than two competing offsets.
    """
    side = spec.side
    p = ax.transData.transform((spec.xi, spec.yi))
    ends = [ax.transData.transform(q) for q in (spec.prev_pt, spec.next_pt) if q is not None]

    extremum = False
    m0 = m1 = None
    if len(ends) == 2:
        dx0 = p[0] - ends[0][0] or 1e-9
        dx1 = ends[1][0] - p[0] or 1e-9
        m0 = (p[1] - ends[0][1]) / dx0
        m1 = (ends[1][1] - p[1]) / dx1
        if math.isfinite(m0) and math.isfinite(m1):
            extremum = (m0 * m1 <= 0)
            if not extremum:
                if abs(m0) >= abs(m1):
                    tx, ty = p[0] - ends[0][0], p[1] - ends[0][1]   # incoming is steeper
                else:
                    tx, ty = ends[1][0] - p[0], ends[1][1] - p[1]   # outgoing is steeper
            else:
                tx, ty = ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]
        else:
            tx, ty = ends[1][0] - ends[0][0], ends[1][1] - ends[0][1]
    elif len(ends) == 1:
        tx, ty = ends[0][0] - p[0], ends[0][1] - p[1]
        extremum = True
    else:
        tx, ty = 1.0, 0.0

    n = math.hypot(tx, ty) or 1.0
    ox, oy = -ty / n, tx / n
    if (side == "above") != (oy > 0):
        ox, oy = -ox, -oy
    # When slope and curvature have opposite signs the right-going lobe of the
    # perpendicular drifts toward the adjacent labelled point; use the left-going
    # lobe instead. For growing+decelerating the m0-based tangent already gives
    # ox < 0, so the guard (ox > 0) means no flip is needed there.
    # Positive curvature (m1 > m0, concave up): take the other perpendicular lobe.
    # The label moves to the concave inside — can land below the data point, which
    # is intentional (e.g. falling+recovering places the label away from the curve).
    # Only applied to "above" marks; "below" marks in multi-series charts must stay
    # below their line and away from the upper series, so standard placement suffices.
    if not extremum and m0 is not None and m1 is not None and m1 > m0 and side == "above":
        ox, oy = -ox, -oy
    return ox, oy, extremum


def _draw_one_line_mark(ax, mark, xi, yi, color, decimals, side, prev_pt, next_pt,
                        placed: list[PlacedMark], theme, xs=(), ys=()) -> None:
    if mark.marker:
        # markersize comes from the theme (rc `lines.markersize`); passing one
        # here would override every theme with a single hard-coded number,
        # which is what it used to do.
        (dot,) = ax.plot([xi], [yi], marker="o", color=color,
                         linestyle="none", zorder=_Z_MARKER)
        dot.set_in_layout(False)
        placed.append(PlacedMark(dot))
    text = _label_text(mark, yi, decimals, theme)
    if text is not None:
        if side == "right":
            ann = _label(ax, text, (xi, yi), (6, 0), "left", "center", color)
            placed.append(PlacedMark(ann, right_anchor=(xi, yi)))  # render may spread + add leaders
        else:
            # offset set in render._finalize_marks (perpendicular to the slope,
            # using the FINAL transform); the PerpSpec carries what that needs.
            ann = _label(ax, text, (xi, yi), (0, 0), "center", "center", color)
            placed.append(PlacedMark(ann, perp=PerpSpec(
                xi, yi, prev_pt, next_pt, side, tuple(xs), tuple(ys))))


def bar_mark(ax, mark, xi, value, color, decimals, theme, placed: list[PlacedMark]) -> None:
    text = _label_text(mark, value, decimals, theme)
    if text is None:
        return
    va, dy = ("bottom", 3) if value >= 0 else ("top", -3)  # on top, or below if negative
    placed.append(PlacedMark(_label(ax, text, (xi, value), (0, dy), "center", va, color)))


def area_mark(ax, mark, xi, top_i, value, color, decimals, theme, placed: list[PlacedMark]) -> None:
    text = _label_text(mark, value, decimals, theme)
    if text is None:
        return
    ann = _label(ax, text, (xi, top_i), (0, 3), "center", "bottom", color)  # just above the curve
    placed.append(PlacedMark(ann))


def stacked_mark(ax, mark, xi, bottom, value, color, decimals, ctx, theme,
                 placed: list[PlacedMark]) -> None:
    text = _label_text(mark, value, decimals, theme)
    if text is None or value == 0:
        return
    y0, y1 = sorted((bottom, bottom + value))
    ann = ax.annotate(text, (xi, (y0 + y1) / 2), ha="center", va="center",
                      fontsize=_LABEL_FONTSIZE, color=theme.label_contrast_color(color),
                      zorder=_Z_LABEL)
    ann.set_in_layout(False)
    # segment box (data coords) so render can hide the label if it doesn't fit.
    placed.append(PlacedMark(ann, fit=SegmentFit(y0, y1, xi, ctx.step * ctx.bar_width_frac)))


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


def _label_text(mark, value, decimals: int, theme) -> str | None:
    if mark.text is not None:
        return mark.text          # custom text replaces the value
    if mark.value:
        return theme.format_number(value, decimals)
    return None


def _label(ax, text, xy, offset, ha, va, color):
    ann = ax.annotate(text, xy, textcoords="offset points", xytext=offset, ha=ha, va=va,
                      fontsize=_LABEL_FONTSIZE, color=color, zorder=_Z_LABEL)
    ann.set_in_layout(False)   # marks never resize the axes (constrained layout ignores them)
    return ann
