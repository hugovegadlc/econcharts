"""Theme engine: load a theme's YAML, apply its form, resolve its colors.

A theme is DATA (`themes/<name>.yaml`): a named color table, a series cycle, the
annotation color vocabulary, and matplotlib rcParams. This module is the generic
machinery that consumes any such file — it holds no theme-specific colors itself.
Color NAMES, defined once in the YAML's `colors`, are referenced everywhere else
(cycle, annotations, rc) and in chart specs; the engine resolves a name to its hex.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pandas as pd
import yaml
from cycler import cycler
from matplotlib.ticker import Formatter

_THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"

_MM_PER_INCH = 25.4

# Named export sizes (physical mm, width x height), from the BBVA add-in's
# export presets. Size is a render-time choice — one spec, many targets.
SIZES_MM: dict[str, tuple[float, float]] = {
    "word_half": (75, 60),
    "word_full": (117, 60),
    "slides_half": (85, 70),
    "slides_full": (140, 75),
}
DEFAULT_SIZE = "slides_half"


def label_contrast_color(fill: str) -> str:
    """White on dark fills, dark navy on light fills — for labels inside a fill."""
    r, g, b = mcolors.to_rgb(fill)
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#FFFFFF" if luminance < 0.55 else "#072146"

# es-PE month/quarter abbreviations (lowercase, no diacritics on the stem).
_MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "set", "oct", "nov", "dic"]


@dataclass(frozen=True)
class Theme:
    """A resolved theme, built from its YAML by `load_theme`.

    `colors` is the full name->hex table; `palette` is the series cycle (hex, in
    order) that `color(i)` indexes; `rc` is the matplotlib rcParams to apply. The
    annotation maps already have their color names resolved to hex.
    """

    name: str
    rc: dict                                   # matplotlib rcParams (colors resolved)
    colors: dict[str, str]                     # color name -> hex (full table)
    palette: list[str]                         # series cycle, hex, in order
    ann_line: dict[str, str] = field(default_factory=dict)   # vocab -> hex
    ann_fill: dict[str, str] = field(default_factory=dict)
    ann_label: dict[str, str] = field(default_factory=dict)
    ann_fill_alpha: float = 0.25
    ann_weights: dict[str, float] = field(default_factory=dict)
    ann_lines: dict[str, str] = field(default_factory=dict)
    date_labels: dict = field(default_factory=dict)   # granularity -> {options, default}

    def style(self):
        """Context manager applying this theme's rcParams (built in memory)."""
        return plt.style.context(self.rc)

    def color(self, i: int) -> str:
        return self.palette[i % len(self.palette)]

    def resolve_color(self, name: str) -> str:
        """A spec's named color (e.g. a series `color:`) -> hex. Errors list choices."""
        try:
            return self.colors[name]
        except KeyError:
            choices = ", ".join(self.colors) or "(none)"
            raise ThemeError(
                f"unknown color {name!r} for theme {self.name!r}; choose from: {choices}"
            ) from None

    def annotation_line_kwargs(self, color: str, weight: str, line: str) -> dict:
        """Resolve a (color, weight, line) annotation vocabulary to matplotlib kwargs."""
        return {
            "color": self.ann_line[color],
            "linewidth": self.ann_weights[weight],
            "linestyle": self.ann_lines[line],
        }

    def annotation_fill_kwargs(self, color: str) -> dict:
        """Resolve a span/band fill color to matplotlib kwargs (no border)."""
        return {"facecolor": self.ann_fill[color], "alpha": self.ann_fill_alpha,
                "linewidth": 0}

    def annotation_label_color(self, color: str) -> str:
        """The annotation's label-text color (a legible shade of its own color)."""
        return self.ann_label[color]

    def date_label(self, period: "pd.Period", granularity: str, style: Optional[str] = None) -> str:
        """Format `period` at a DISPLAY `granularity` (D/M/Q/Y, may be coarser than
        the period's own freq) using one of the theme's named styles for that
        granularity (or its default). Tokens: {yyyy}{yy}{q}{mmm}{d}."""
        conf = self.date_labels.get(granularity)
        if conf is None:
            raise ThemeError(f"theme {self.name!r} defines no date labels for {granularity!r}")
        style = style or conf["default"]
        try:
            pattern = conf["options"][style]
        except KeyError:
            raise ThemeError(
                f"unknown date-label style {style!r} for {granularity}; "
                f"choose from: {', '.join(conf['options'])}"
            ) from None
        p = period if period.freqstr[0] == granularity else period.asfreq(granularity)
        fields = {"yyyy": f"{p.year:04d}", "yy": f"{p.year % 100:02d}"}
        if granularity == "Q":
            fields["q"] = str(p.quarter)
            fields["mmm"] = _MONTHS_ES[p.quarter * 3 - 1]   # quarter's closing month
        elif granularity == "M":
            fields["mmm"] = _MONTHS_ES[p.month - 1]
        elif granularity == "D":
            fields["d"], fields["mmm"] = str(period.day), _MONTHS_ES[period.month - 1]
        return pattern.format(**fields)

    @staticmethod
    def figsize(size: str) -> tuple[float, float]:
        """Resolve a named export size to a matplotlib figsize in inches."""
        if size not in SIZES_MM:
            raise ThemeError(f"unknown size {size!r}; choose from {sorted(SIZES_MM)}")
        w_mm, h_mm = SIZES_MM[size]
        return (w_mm / _MM_PER_INCH, h_mm / _MM_PER_INCH)


def load_theme(name: str) -> Theme:
    """Load and resolve a theme from `themes/<name>.yaml`."""
    path = _THEMES_DIR / f"{name}.yaml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in _THEMES_DIR.glob("*.yaml"))) or "(none)"
        raise ThemeError(f"unknown theme {name!r}; available: {available}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    colors = {k: str(v) for k, v in raw.get("colors", {}).items()}

    def resolve(v):  # a value that names a color -> its hex; anything else untouched
        return colors.get(v, v) if isinstance(v, str) else v

    try:
        palette = [colors[n] for n in raw["cycle"]]
    except KeyError as e:
        raise ThemeError(f"theme {name!r}: cycle names an undefined color {e}") from None

    rc = {k: resolve(v) for k, v in raw.get("rc", {}).items()}
    rc["axes.prop_cycle"] = cycler("color", palette)

    ann = raw.get("annotations", {})
    return Theme(
        name=name,
        rc=rc,
        colors=colors,
        palette=palette,
        ann_line={k: resolve(v) for k, v in ann.get("line", {}).items()},
        ann_fill={k: resolve(v) for k, v in ann.get("fill", {}).items()},
        ann_label={k: resolve(v) for k, v in ann.get("label", {}).items()},
        ann_fill_alpha=ann.get("fill_alpha", 0.25),
        ann_weights=ann.get("weights", {}),
        ann_lines=ann.get("lines", {}),
        date_labels=raw.get("date_labels", {}),
    )


class ThemeError(ValueError):
    """Theme could not be resolved."""


# --- es-PE period formatting -------------------------------------------------

def format_period(period: pd.Period) -> str:
    """Format a single pandas Period in es-PE style for axis ticks."""
    freq = period.freqstr[0]
    if freq == "Q":
        return f"{period.quarter}T{period.year % 100:02d}"
    if freq == "M":
        return f"{_MONTHS_ES[period.month - 1]} {period.year}"
    return str(period.year)


def es_pe(value: float, decimals: int = 0) -> str:
    """Format a number es-PE: '.' thousands separator, ',' decimal separator."""
    s = f"{value:,.{decimals}f}"  # en-US: ',' thousands, '.' decimal
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def value_decimals(value: float, cap: int = 2) -> int:
    """Minimal decimals needed to show `value` exactly (trailing zeros stripped, capped)."""
    for d in range(cap):
        if round(value, d) == round(value, cap):
            return d
    return cap


def es_pe_value(value: float, cap: int = 2) -> str:
    """es-PE value label with the minimal decimals. 76->'76', 3.8->'3,8', 3.85->'3,85'."""
    return es_pe(value, value_decimals(value, cap))


class EsPeNumber(Formatter):
    """es-PE y-axis tick formatter with decimals chosen from the tick spacing.

    A single fixed number of decimals breaks on small-magnitude axes (e.g. an
    exchange rate where 3.75 and 3.80 would both round to '3,8'). This reads the
    actual tick locations and uses just enough decimals to keep them distinct.
    """

    def set_locs(self, locs):
        self.locs = locs
        steps = [abs(b - a) for a, b in zip(sorted(locs), sorted(locs)[1:]) if b != a]
        step = min(steps) if steps else 1.0
        self._decimals = 0 if step >= 1 else int(math.ceil(-math.log10(step)))

    def __call__(self, x, pos=None):
        return es_pe(x, getattr(self, "_decimals", 0))
