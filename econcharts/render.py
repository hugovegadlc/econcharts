"""Orchestration: spec -> matplotlib Figure -> output backend.

Step 1 scope: `line` series on the primary axis, `png` backend, bbva theme.
Bars/areas/secondary axis (step 3) and annotations (step 4) slot in later.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Union

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.transforms import Bbox

from econcharts.errors import EconchartsError
from econcharts import annotations as _annotations
from econcharts import charttypes
from econcharts import marks as _marks
from econcharts import timeaxis
from econcharts.data import (
    DataResolver,
    clip_to_window,
    parse_period,
    parse_window_spec,
)
from econcharts.spec import Series, Spec
from econcharts.theme import (
    DEFAULT_SIZE,
    EsPeNumber,
    Theme,
    ThemeError,
    format_period,
    load_theme,
)

# No bbox_inches="tight": that would crop to content and break the exact named
# size. The figure is laid out (constrained) to fit content WITHIN its figsize,
# so it always saves at the named physical size.
_BACKENDS = {
    "png": dict(dpi=300, transparent=True),
    "pdf": dict(),
    "svg": dict(),
}


class RenderError(EconchartsError):
    """A spec was valid but could not be rendered."""


def _periods_to_x(periods) -> np.ndarray:
    """The one place periods become axis x-coordinates (matplotlib date numbers).

    Each period maps to its MIDPOINT, not its start, so bars fill the period and
    line points / tick labels sit centered under each period (e.g. the "1T22"
    bar is centered within Q1, not on the Q4->Q1 boundary).
    """
    out = []
    for p in periods:
        span = p.end_time - p.start_time
        out.append(mdates.date2num(p.start_time + span / 2))
    return np.asarray(out, dtype=float)


def _date_to_x(token: str) -> float:
    """Period token -> axis x at the period MIDPOINT (line/area: the data point)."""
    return float(_periods_to_x([parse_period(token)])[0])


def _date_to_boundary(token: str) -> float:
    """Period token -> axis x at the period's leading EDGE (bar/stacked: between bars)."""
    return float(mdates.date2num(parse_period(token).start_time))


def _date_to_end(token: str) -> float:
    """Period token -> axis x at the period's trailing edge (for span ranges)."""
    return float(mdates.date2num(parse_period(token).end_time))


def render(spec: Spec, size: str = DEFAULT_SIZE, data_root=None) -> Figure:
    """Render a validated spec to a matplotlib Figure (not yet saved).

    `size` selects a named BBVA export preset (e.g. "slides_full", "slides_half").
    `data_root` is where relative workbook paths in `excel:` refs resolve
    (defaults to the ECONCHARTS_DATA_ROOT env var, else the current directory).
    """
    theme = load_theme(spec.theme)
    long_df, window = _resolve_framed(spec, data_root)

    # Validate spec.style overrides before any drawing — a bad rcParam key or
    # value surfaces here as a RenderError, not a cryptic matplotlib traceback.
    if spec.style:
        try:
            with plt.style.context(spec.style):
                pass
        except (KeyError, ValueError) as e:
            raise RenderError(f"style: invalid rcParam override — {e}") from None

    rc = {**theme.rc, **spec.style} if spec.style else theme.rc
    with plt.style.context(rc):
        # constrained layout fits content (title, ticks, legend) by resizing the
        # AXES inside a fixed-size figure — the figure never grows to fit content.
        fig, ax = plt.subplots(figsize=theme.figsize(size), layout="constrained")
        ax2 = ax.twinx() if any(s.axis == "secondary" for s in spec.series) else None
        placed, placed2 = _draw_series(ax, ax2, spec, long_df, theme)
        has_bars = any(s.type in ("bar", "stacked") for s in spec.series)
        # vlines sit BETWEEN bars (period boundary) on bar/stacked charts, but AT
        # the data point (midpoint) on line/area charts; span edges always snap to
        # period boundaries (covering whole periods).
        coords = _annotations.AxisCoords(
            vline=_date_to_boundary if has_bars else _date_to_x,
            span_start=_date_to_boundary,
            span_end=_date_to_end,
        )
        _annotations.draw_annotations(ax, spec, coords, theme)
        _validate_date_label(spec, theme)
        _apply_axes(ax, spec, long_df, has_bars, window, theme)
        if ax2 is not None:
            _apply_secondary_axis(ax2, spec)
        _apply_titles(ax, spec, theme)
        _apply_legend(fig, ax, ax2, spec)
        # marks (dots/value labels): hide stacked labels that don't fit their
        # segment, then grow the axis limits so edge labels aren't clipped.
        for a, a_placed in ((ax, placed), (ax2, placed2)):
            if a is not None:
                _finalize_marks(a, a_placed, theme)
    return fig


def save(fig: Figure, out: Union[str, Path], backend: Optional[str] = None) -> Path:
    """Save a rendered Figure via the named output backend (inferred from suffix)."""
    out = Path(out)
    backend = backend or out.suffix.lstrip(".").lower()
    if backend not in _BACKENDS:
        raise RenderError(f"unknown backend {backend!r}; choose from {sorted(_BACKENDS)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, format=backend, **_BACKENDS[backend])
    return out


# --- resolve + frame ---------------------------------------------------------

def _resolve_framed(spec: Spec, data_root):
    """Resolve the spec's data and the axis frame (the `period` window).

    Two phases so a `period: …:end` can be answered: (1) resolve the series that
    carry their own periods (excel refs, {period: value} maps) and read the
    sample's latest period; (2) materialize the window (filling an open `end`),
    align any inline-LIST series to it, then clip everything to the frame.
    Returns (long_df, window) where `window` is the PeriodIndex frame (or None).
    """
    wspec = parse_window_spec(spec.period) if spec.period else None
    resolver = DataResolver(data_root=data_root)

    # Phase 1: series with intrinsic periods (refs + inline {period: value} maps).
    natural: dict[str, pd.DataFrame] = {
        s.name: resolver.resolve_series(s)
        for s in spec.series if not isinstance(s.data, list)
    }
    # The sample's first/last period = the min/max across dated series (NOT any one
    # series' own first/last point — that distinction matters for `mark: last`).
    dated = [df for df in natural.values() if not df.empty]
    sample_min = min((df["period"].min() for df in dated), default=None)
    sample_max = max((df["period"].max() for df in dated), default=None)
    window = wspec.materialize(sample_min, sample_max) if wspec is not None else None

    # Phase 2: inline-list series align positionally to the concrete frame.
    resolver.window = window
    frames = [natural[s.name] if s.name in natural else resolver.resolve_series(s)
              for s in spec.series]
    long_df = pd.concat(frames, ignore_index=True)
    return clip_to_window(long_df, window), window


# --- drawing -----------------------------------------------------------------

def _draw_series(ax, ax2, spec: Spec, long_df: pd.DataFrame, theme: Theme):
    """Route each series to its axis (primary or secondary) and draw the group.

    Stacking/grouping accumulators are independent per axis; the palette color is
    keyed to the GLOBAL series index so colors stay consistent across both.
    Returns the two axes' PlacedMark lists for `_finalize_marks`.
    """
    ctx = _build_context(long_df)
    indexed = list(enumerate(spec.series))
    placed = _draw_group(ax, [(i, s) for i, s in indexed if s.axis == "primary"],
                         long_df, theme, ctx)
    placed2: list = []
    if ax2 is not None:
        placed2 = _draw_group(ax2, [(i, s) for i, s in indexed if s.axis == "secondary"],
                              long_df, theme, ctx)
    return placed, placed2


def _draw_group(ax, items, long_df: pd.DataFrame, theme: Theme,
                ctx: charttypes.RenderContext) -> list[_marks.PlacedMark]:
    """Draw a set of (global_index, series) onto one Axes, with its own stacking.

    All type-specific behaviour (stacking, dodging, mark placement) lives on the
    strategy classes in `charttypes.CHART_TYPES`; this loop just walks the series
    in spec order with the group's shared accumulator state. Returns the marks
    placed on this axes (the records `_finalize_marks` post-processes).
    """
    state = charttypes.GroupState(bar_count=sum(1 for _, s in items if s.type == "bar"))
    mark_decimals = _mark_decimals(items, long_df)  # consistent decimals across the axis
    line_marks: list = []   # collected so line label sides can be chosen across series
    placed: list[_marks.PlacedMark] = []
    for i, s in items:
        sub = long_df[long_df["series"] == s.name].sort_values("period")
        periods = list(sub["period"])
        x = _periods_to_x(periods)
        y = sub["value"].to_numpy(dtype=float)
        try:
            color = theme.resolve_color(s.color) if s.color else theme.color(i)
        except ThemeError as e:
            raise RenderError(f"series {s.name!r}: {e}") from None
        ctype = charttypes.chart_type(s.type)
        try:
            geom = ctype.draw(ax, s, x, y, periods, color, ctx, state, theme)
        except (charttypes.ChartTypeError, ThemeError) as e:
            raise RenderError(f"series {s.name!r}: {e}") from None
        if s.mark is not None:
            if ctype.defer_marks:
                line_marks.append((s, periods, x, y, color))
            else:
                ctype.place_marks(ax, s, periods, x, y, color, mark_decimals, ctx, geom,
                                  theme, placed)
    if line_marks:
        _marks.draw_line_marks(ax, line_marks, mark_decimals, placed)
    return placed


def _finalize_marks(ax, placed: list[_marks.PlacedMark], theme: Theme) -> None:
    """Post-draw mark cleanup: hide stacked labels that don't fit their segment,
    then grow xlim/ylim so the remaining dots/labels aren't clipped at an edge.

    `placed` is the explicit record list mark placement produced — each entry is
    one artist plus the adjustment its kind needs (see marks.PlacedMark).
    """
    if not placed:
        return
    fig = ax.figure
    base_xlim, base_ylim = ax.get_xlim(), ax.get_ylim()  # intended limits, before any moves
    fig.draw_without_rendering()
    renderer = fig.canvas.get_renderer()

    # 1) stacked labels: hide any that don't fit their segment (height or width).
    for pm in placed:
        if pm.fit is None:
            continue
        f = pm.fit
        seg_h = abs(ax.transData.transform((f.xc, f.y1))[1] - ax.transData.transform((f.xc, f.y0))[1])
        bar_px = abs(ax.transData.transform((f.xc + f.bar_w / 2, f.y0))[0]
                     - ax.transData.transform((f.xc - f.bar_w / 2, f.y0))[0])
        bb = pm.artist.get_window_extent(renderer)
        if bb.height > seg_h or bb.width > bar_px:
            pm.artist.set_visible(False)

    # 1b) above/below line labels: offset perpendicular to the line's local slope
    #     (final transform), by the label's own reach along that direction plus a
    #     constant gap — so the clearance is the same on flat and steep sections.
    moved = False
    dpi72 = fig.dpi / 72.0
    for pm in placed:
        if pm.perp is None:
            continue
        ox, oy = _marks.perp_unit(ax, pm.perp)
        bb = pm.artist.get_window_extent(renderer)
        reach = abs(ox) * (bb.width / 2) + abs(oy) * (bb.height / 2)   # px toward the line
        dist = reach / dpi72 + _marks.PERP_GAP                          # -> points
        pm.artist.xyann = (ox * dist, oy * dist)
        moved = True

    # 1c) right-of-endpoint labels (3+ lines at the last point): if their endpoints
    #     are too close, spread them evenly (value order kept) with leader lines.
    if _spread_right_labels(ax, renderer, theme, placed):
        moved = True
    if moved:
        fig.draw_without_rendering()
        renderer = fig.canvas.get_renderer()

    # (Other line-label crowding is handled by side selection in
    # marks.draw_line_marks — labels sit on the outer side of the curve.)

    # 2) grow limits to contain the visible marks, but CAP the growth (from the
    #    intended limits) so scattered labels overflow/clip rather than squish data.
    inv = ax.transData.inverted()
    (x0, x1), (y0, y1) = base_xlim, base_ylim
    xspan, yspan = abs(x1 - x0), abs(y1 - y0)
    xmin, xmax = min(x0, x1), max(x0, x1)
    ymin, ymax = min(y0, y1), max(y0, y1)
    for pm in placed:
        a = pm.artist
        if not a.get_visible():
            continue
        bb = a.get_window_extent(renderer)
        if isinstance(a, Line2D) and a.get_marker() not in (None, "None", ""):
            pad = a.get_markersize() * fig.dpi / 72.0 * 0.6  # ~marker radius, in px
            bb = Bbox.from_extents(bb.x0 - pad, bb.y0 - pad, bb.x1 + pad, bb.y1 + pad)
        for cx, cy in inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)]):
            xmin, xmax = min(xmin, cx), max(xmax, cx)
            ymin, ymax = min(ymin, cy), max(ymax, cy)
    cap = 0.25  # generous sanity bound (labels sit near points, so this rarely bites)
    xmin, xmax = max(xmin, min(x0, x1) - cap * xspan), min(xmax, max(x0, x1) + cap * xspan)
    ymin, ymax = max(ymin, min(y0, y1) - cap * yspan), min(ymax, max(y0, y1) + cap * yspan)
    ax.set_xlim(xmin, xmax) if x0 <= x1 else ax.set_xlim(xmax, xmin)
    ax.set_ylim(ymin, ymax) if y0 <= y1 else ax.set_ylim(ymax, ymin)


def _spread_right_labels(ax, renderer, theme: Theme,
                         placed: list[_marks.PlacedMark]) -> bool:
    """Vertically separate right-of-endpoint labels when their points are too
    close, preserving value order, and draw a leader from each label to its point.
    Returns True if anything moved (so the caller re-measures)."""
    labels = [(pm.artist, pm.right_anchor) for pm in placed if pm.right_anchor is not None]
    if len(labels) < 2:
        return False
    dpi72 = ax.figure.dpi / 72.0
    info = []
    for L, (xi, yi) in labels:
        adx, ady = ax.transData.transform((xi, yi))
        bb = L.get_window_extent(renderer)
        info.append((L, xi, yi, adx, ady, bb.height))
    info.sort(key=lambda t: t[2], reverse=True)           # value desc -> top first
    gap = max(t[5] for t in info) * 1.2                    # min spacing (px)
    natural = [t[4] for t in info]
    if all(natural[k] - natural[k + 1] >= gap for k in range(len(natural) - 1)):
        return False                                       # already separated
    center = sum(natural) / len(natural)
    targets = [center + (len(info) - 1) * gap / 2 - k * gap for k in range(len(info))]
    for (L, xi, yi, adx, ady, _h), ty in zip(info, targets):
        dx, _ = L.xyann
        L.xyann = (dx, (ty - ady) / dpi72)                 # move label to its slot
        ex, ey = ax.transData.inverted().transform((adx + dx * dpi72, ty))
        leader, = ax.plot([xi, ex], [yi, ey], color=theme.colors["leadergrey"], lw=0.6, zorder=3.8)
        leader.set_in_layout(False)
    return True


def _mark_decimals(items, long_df: pd.DataFrame) -> int:
    """One decimal count for every value label on an axis (the max any one needs)."""
    values: list = []
    for _, s in items:
        if s.mark is None:
            continue
        sub = long_df[long_df["series"] == s.name].sort_values("period")
        values += _marks.marked_values(s, list(sub["period"]), sub["value"].to_numpy(dtype=float))
    return _marks.decimals_for(values)


def _build_context(long_df: pd.DataFrame) -> charttypes.RenderContext:
    """Common geometry: the median x spacing between periods (for bar widths)."""
    periods = sorted(long_df["period"].unique())
    xs = _periods_to_x(periods)
    step = float(np.median(np.diff(xs))) if len(xs) > 1 else 30.0
    return charttypes.RenderContext(step=step)


def _validate_date_label(spec: Spec, theme: Theme) -> None:
    """A chart's `date_label` must name a style defined for some granularity (it is
    applied per-granularity where valid). Catch typos early with the valid choices."""
    if spec.date_label is None:
        return
    valid = {s for g in theme.date_labels.values() for s in g.get("options", {})}
    if spec.date_label not in valid:
        raise RenderError(
            f"unknown date_label {spec.date_label!r}; choose from: {', '.join(sorted(valid))}"
        )


def _apply_axes(ax, spec: Spec, long_df: pd.DataFrame, has_bars: bool, window,
                theme: Theme) -> None:
    # The axis spans the declared `period` window when there is one (authoritative
    # frame), else the data's own range. Ticks and x-limits both come from the frame
    # so a chart shows its whole window even where a series has no data.
    frame = list(window) if window is not None else sorted(long_df["period"].unique())
    _set_period_ticks(ax, frame, boundary_marks=has_bars, theme=theme, style=spec.date_label)
    ax.set_axisbelow(True)  # grid behind all artists (bars, areas, lines)
    ax.yaxis.set_major_formatter(EsPeNumber())
    if window is not None and frame:
        # Extend the x data-limits to the frame ends. update_datalim leaves y alone
        # when the y we pass sits inside the existing data range; when the data
        # already fills the window these x's are existing points, so it's a no-op.
        xs = _periods_to_x([frame[0], frame[-1]])
        ymin, ymax = ax.dataLim.intervaly
        yc = (ymin + ymax) / 2 if np.isfinite([ymin, ymax]).all() else 0.0
        ax.update_datalim([(xs[0], yc), (xs[-1], yc)])
    ax.margins(x=0.01)
    if spec.ylabel:
        ax.set_ylabel(spec.ylabel)


def _apply_secondary_axis(ax2, spec: Spec) -> None:
    """Style the right-hand twin: no grid of its own, es-PE ticks, y2label.

    Only the primary axis draws the gridlines; the twin shares the x-axis so it
    must not redraw x ticks. Its background is hidden so primary content shows.
    """
    ax2.grid(False)
    ax2.patch.set_visible(False)
    ax2.yaxis.set_major_formatter(EsPeNumber())
    ax2.tick_params(axis="x", bottom=False, labelbottom=False, top=False, labeltop=False)
    if spec.y2label:
        ax2.set_ylabel(spec.y2label, rotation=270, va="bottom")


def _set_period_ticks(ax, periods: list[pd.Period], *, boundary_marks: bool,
                      theme: Theme, style=None) -> None:
    """Place x ticks. `timeaxis.plan_ticks` chooses the display granularity + which
    periods carry labels (adaptive to width); `style` is the chart's label-style pick.

    Two regimes:
      * `boundary_marks` (charts with bars): MARKS sit on the period boundaries
        between bars (major, unlabeled), LABELS centered under the chosen bars
        (minor, no marks).
      * otherwise (line/area): a tick points AT its data point, so the mark and
        its label coincide at the period midpoint.
    """
    if not periods:
        return
    width_in = ax.figure.get_size_inches()[0]
    ticks = timeaxis.plan_ticks(periods, width_in, theme, style)  # [(period, text)]
    label_x = _periods_to_x([p for p, _ in ticks])
    labels = [t for _, t in ticks]

    if not boundary_marks:
        ax.set_xticks(label_x)
        ax.set_xticklabels(labels)
        return

    # Bars: separator marks on EVERY bar boundary (major, unlabeled) — each
    # period's leading edge plus the closing edge of the series.
    boundaries = [mdates.date2num(p.start_time) for p in periods]
    boundaries.append(mdates.date2num(periods[-1].end_time))
    ax.set_xticks(boundaries)
    ax.set_xticklabels([""] * len(boundaries))
    # Labels centered under the chosen bars (minor ticks, no marks).
    ax.set_xticks(label_x, minor=True)
    ax.set_xticklabels(labels, minor=True)
    ax.tick_params(axis="x", which="minor", length=0)


def _apply_titles(ax, spec: Spec, theme: Theme) -> None:
    # `source` is kept as spec metadata but intentionally NOT drawn: the BBVA
    # chart formatter never renders a source on the chart (it lives on the
    # slide/worksheet beside it). See spec.Spec.source.
    # title and subtitle are both optional. When absent (None or blank) nothing
    # is drawn, so constrained layout lets the axes fill the freed space.
    # wrap=True lets a long title/subtitle flow onto extra lines instead of
    # overflowing the fixed canvas; constrained layout reserves the height.
    if spec.title:
        ax.set_title(spec.title, pad=16 if spec.subtitle else 8, wrap=True)
        if spec.subtitle:
            ax.annotate(
                spec.subtitle,
                xy=(0, 1), xycoords="axes fraction",
                xytext=(0, 5), textcoords="offset points",
                ha="left", va="bottom", fontsize=8, color=theme.colors["slate"], wrap=True,
            )
    elif spec.subtitle:
        # subtitle but no title: render it in the title slot with subtitle style
        # so its height is still reserved.
        ax.set_title(spec.subtitle, pad=8, wrap=True,
                     fontsize=8, color=theme.colors["slate"], fontweight="normal")


def _apply_legend(fig, ax, ax2, spec: Spec) -> None:
    # One combined legend across both axes (primary handles first, then secondary).
    handles, labels = ax.get_legend_handles_labels()
    if ax2 is not None:
        h2, l2 = ax2.get_legend_handles_labels()
        handles, labels = handles + h2, labels + l2
    if not (len(labels) > 1 or spec.series[0].label):
        return
    # A figure-level legend placed OUTSIDE, bottom-left: constrained layout
    # reserves room for it inside the fixed canvas. Wrap to as many rows as
    # needed so a wide legend row never overflows the fixed width.
    fig.legend(
        handles, labels,
        loc="outside lower left",
        ncol=_legend_columns(labels, fig.get_figwidth()),
    )


def _legend_columns(labels, fig_width_in: float, fontsize: float = 8.0) -> int:
    """Largest column count whose widest row still fits the figure width.

    Estimates each entry's width (handle + text) in points and picks the most
    columns such that the `ncol` widest entries fit one row — guaranteeing no
    row overflows, so the legend wraps instead of clipping.
    """
    per_char = 0.6 * fontsize
    handle = 2.0 * fontsize + 8.0  # marker line + gaps + padding
    widths = sorted((handle + per_char * len(str(l)) for l in labels), reverse=True)
    avail = fig_width_in * 72.0 * 0.95
    for ncol in range(len(labels), 0, -1):
        if sum(widths[:ncol]) <= avail:
            return ncol
    return 1
