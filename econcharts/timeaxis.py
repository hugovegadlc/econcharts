"""Temporal-axis intelligence: choose how a date axis is labelled.

Given the frame's periods (at the data's own freq), the axis width, and the theme,
decide a DISPLAY granularity (D/M/Q/Y, never finer than the data) and which periods
carry labels — so daily data over a year reads in months, monthly over a decade in
years. The renderer turns the returned periods into x-positions and draws them; this
module is pure (periods + theme in, (period, label) pairs out).

The rule, finest granularity first: if its labels fit, show them all; if they only
mildly overflow, thin every-other and stay; only on larger overflow drop to the next
coarser granularity (years, ultimately, thinned as far as needed). So a short span
keeps quarters/months, a long one switches to years — both *and* skipping ticks.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import pandas as pd

    from econcharts.theme import Theme

# Coarsening ladder per data freq: finest candidate first.
_LADDER = {
    "D": ["D", "M", "Q", "Y"],
    "M": ["M", "Q", "Y"],
    "Q": ["Q", "Y"],
    "Y": ["Y"],
}


def _gran_of(period: "pd.Period") -> str:
    return period.freqstr[0]


def _gran_start(g: "pd.Period", data_freq: str) -> "pd.Period":
    """The canonical start of a gran period expressed in data_freq.

    E.g. year 2024 in monthly data → 2024M01. Used as the x-position so that
    thinned ticks are evenly spaced regardless of where the data window begins.
    """
    if _gran_of(g) == data_freq:
        return g
    return g.asfreq(data_freq, how="start")


def _representatives(periods: list, gran: str) -> list:
    """One (x_period, gran_period) per distinct granularity-period, in order.

    x_period is the START of the gran bucket expressed in the data's own freq
    (e.g. 2024M01 for year 2024 in monthly data). This makes tick spacing
    uniform after thinning — positioning by the first observed data point
    instead would shift the first tick when the window starts mid-period.
    """
    out, seen = [], set()
    data_freq = _gran_of(periods[0]) if periods else gran
    for p in periods:
        g = p if _gran_of(p) == gran else p.asfreq(gran)
        key = str(g)
        if key not in seen:
            seen.add(key)
            out.append((_gran_start(g, data_freq), g))
    return out


def _style_for(theme: "Theme", gran: str, preferred: Optional[str]) -> Optional[str]:
    """Apply a chart's preferred label style only where the chosen granularity
    actually defines it; otherwise fall back to that granularity's default."""
    options = theme.date_labels.get(gran, {}).get("options", {})
    return preferred if preferred in options else None


# How aggressively we thin within a granularity before dropping to a coarser one:
# step 2 (every-other) is fine; a coarser granularity is cleaner than skipping 2-of-3.
_THIN_MAX_STEP = 2


def max_labels_for(width_in: float, rotation: int = 0) -> int:
    """How many date labels fit the axis width.

    Rotated labels have a smaller horizontal footprint, so more fit.
    At 270° (reading upward) the footprint is just the font height — cap
    the scaling at cos(80°) ≈ 0.17 to avoid exploding the count.
    """
    scale = 1.0 / max(0.17, math.cos(math.radians(abs(rotation) % 180)))
    return max(2, round(width_in * 1.8 * scale))


def plan_ticks(periods, width_in: float, theme: "Theme",
               style: Optional[str] = None,
               rotation: int = 0) -> list:
    """Return [(period, label_text), …] — the periods to label and their text.

    `periods` is the frame's periods (sorted, one freq). `style` is a chart's
    preferred label style, honoured per granularity where defined. `rotation`
    is the label rotation in degrees (0 = horizontal, 270 = reading upward).
    """
    periods = sorted(periods)
    if not periods:
        return []
    max_labels = max_labels_for(width_in, rotation)
    ladder = _LADDER.get(_gran_of(periods[0]), [_gran_of(periods[0])])
    last = ladder[-1]

    frame_start = periods[0]

    for gran in ladder:
        reps = _representatives(periods, gran)
        step = max(1, -(-len(reps) // max_labels))  # ceil division
        # Use this granularity if it fits, only mildly overflows (thin every-other),
        # or it's the coarsest rung (then thin as far as needed).
        if step <= _THIN_MAX_STEP or gran == last:
            reps = list(reversed(reps[::-step]))
            # Drop any tick whose canonical x-position falls before the frame —
            # this happens when the window starts mid-period (e.g. 1993M12 with
            # yearly ticks: 1993Y maps to 1993M01 which is before the frame).
            return [(rp, theme.date_label(gp, gran, _style_for(theme, gran, style)))
                    for rp, gp in reps if rp >= frame_start]
    return []  # unreachable: the coarsest rung always returns
