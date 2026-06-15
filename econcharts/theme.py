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
from econcharts.errors import EconchartsError
import matplotlib.pyplot as plt
import pandas as pd
import yaml
from cycler import cycler
from matplotlib.ticker import Formatter

_THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"

_MM_PER_INCH = 25.4

# The default named size; the actual mm for each name live in the theme YAML.
DEFAULT_SIZE = "slides_half"

# Fixed annotation vocabularies — every theme must cover these roles.
_ANN_ROLES = ("grey", "orange", "blue")
_ANN_WEIGHTS = ("thin", "thick")
_ANN_LINE_STYLES = ("solid", "dotted")
_DATE_GRAN = ("D", "M", "Q", "Y")

# Where a theme puts the chart legend (a chart spec may override by name).
# `below`/`above` are figure-level horizontal rows outside the axes (constrained
# layout reserves room); the four corners sit INSIDE the axes (ggplot-style),
# stacked vertically, reserving nothing — the author owns collision risk.
LEGEND_POSITIONS = ("below", "above", "top-left", "top-right", "bottom-left", "bottom-right")



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
    highlight: Optional[str] = None                   # default bar-highlight hex
    legend_position: str = "below"                    # one of LEGEND_POSITIONS
    sizes_mm: dict = field(default_factory=dict)  # name -> (w_mm, h_mm); populated from theme yaml
    num_thousands: str = "."  # thousands separator used by format_number
    num_decimal: str = ","    # decimal separator used by format_number
    source_prefix: str = "Fuente:"

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

    def highlight_color(self) -> str:
        """The default bar-highlight hex (when a spec's `highlight` names no color)."""
        if self.highlight is None:
            raise ThemeError(
                f"theme {self.name!r} defines no `highlight` color; "
                f"set `highlight.color` in the spec or add `highlight:` to the theme"
            )
        return self.highlight

    def label_contrast_color(self, fill: str) -> str:
        """White on dark fills, ink on light fills — for labels drawn inside a fill."""
        r, g, b = mcolors.to_rgb(fill)
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return self.colors["white"] if luminance < 0.55 else self.colors["ink"]

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

    def format_number(self, value: float, decimals: int = 0) -> str:
        """Format a number using the theme's thousands/decimal separators."""
        s = f"{value:,.{decimals}f}"      # en-US base: ',' thousands, '.' decimal
        return (s.replace(",", "\x00")
                 .replace(".", self.num_decimal)
                 .replace("\x00", self.num_thousands))

    def figsize(self, size: str) -> tuple[float, float]:
        """Resolve a named export size to a matplotlib figsize in inches.

        Theme-level `sizes:` entries take precedence over the global defaults,
        so different themes can ship different physical dimensions for the same
        size name (e.g. macro's slides_full is 200×150 mm, not 140×75 mm).
        """
        if size not in self.sizes_mm:
            raise ThemeError(f"unknown size {size!r}; choose from {sorted(self.sizes_mm)}")
        w_mm, h_mm = self.sizes_mm[size]
        return (w_mm / _MM_PER_INCH, h_mm / _MM_PER_INCH)


def _validate_theme(name: str, raw: dict, sizes_mm: dict) -> None:
    """Raise ThemeError if any required section is absent or structurally incomplete.

    Required: sizes (≥1 entry), annotations (line/fill/label with all three color
    roles; weights with thin/thick; lines with solid/dotted), date_labels (all four
    granularities D/M/Q/Y, each with a non-empty options map and a valid default).
    colors and cycle are validated earlier in load_theme.
    """
    nf = raw.get("number_format")
    if not isinstance(nf, dict):
        raise ThemeError(f"theme {name!r}: `number_format` section is required")
    for key in ("thousands", "decimal"):
        if key not in nf:
            raise ThemeError(f"theme {name!r}: `number_format.{key}` is required")

    if not sizes_mm:
        raise ThemeError(
            f"theme {name!r}: `sizes` is required — declare at least one named size"
        )

    ann = raw.get("annotations")
    if not isinstance(ann, dict):
        raise ThemeError(f"theme {name!r}: `annotations` section is required")
    for sub in ("line", "fill", "label"):
        m = ann.get(sub)
        if not isinstance(m, dict):
            raise ThemeError(f"theme {name!r}: `annotations.{sub}` is required")
        missing = [r for r in _ANN_ROLES if r not in m]
        if missing:
            raise ThemeError(
                f"theme {name!r}: `annotations.{sub}` must define all three roles "
                f"({', '.join(_ANN_ROLES)}); missing: {', '.join(missing)}"
            )
    for sub, vocab in (("weights", _ANN_WEIGHTS), ("lines", _ANN_LINE_STYLES)):
        m = ann.get(sub)
        if not isinstance(m, dict):
            raise ThemeError(f"theme {name!r}: `annotations.{sub}` is required")
        missing = [k for k in vocab if k not in m]
        if missing:
            raise ThemeError(
                f"theme {name!r}: `annotations.{sub}` must define: {', '.join(missing)}"
            )

    dl = raw.get("date_labels")
    if not isinstance(dl, dict):
        raise ThemeError(f"theme {name!r}: `date_labels` section is required")
    for gran in _DATE_GRAN:
        if gran not in dl:
            raise ThemeError(
                f"theme {name!r}: `date_labels.{gran}` is required "
                f"(needed granularities: {', '.join(_DATE_GRAN)})"
            )
        conf = dl[gran]
        if not isinstance(conf.get("options"), dict) or not conf["options"]:
            raise ThemeError(
                f"theme {name!r}: `date_labels.{gran}.options` must be a non-empty mapping"
            )
        dflt = conf.get("default")
        if dflt is None:
            raise ThemeError(
                f"theme {name!r}: `date_labels.{gran}.default` is required"
            )
        if dflt not in conf["options"]:
            raise ThemeError(
                f"theme {name!r}: `date_labels.{gran}.default` {dflt!r} "
                f"not in options: {list(conf['options'])}"
            )


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

    if "cycle" not in raw:
        raise ThemeError(f"theme {name!r}: `cycle` is required")
    try:
        palette = [colors[n] for n in raw["cycle"]]
    except KeyError as e:
        raise ThemeError(f"theme {name!r}: cycle names an undefined color {e}") from None
    if not palette:
        raise ThemeError(f"theme {name!r}: `cycle` must list at least one color name")

    rc = {k: resolve(v) for k, v in raw.get("rc", {}).items()}
    rc["axes.prop_cycle"] = cycler("color", palette)

    highlight_name = raw.get("highlight")
    if highlight_name is not None and highlight_name not in colors:
        raise ThemeError(
            f"theme {name!r}: highlight names an undefined color {highlight_name!r}"
        )

    legend_position = (raw.get("legend") or {}).get("position", "below")
    if legend_position not in LEGEND_POSITIONS:
        raise ThemeError(
            f"theme {name!r}: unknown legend position {legend_position!r}; "
            f"choose from: {', '.join(LEGEND_POSITIONS)}"
        )

    sizes_mm = {k: tuple(v) for k, v in raw.get("sizes", {}).items()}
    _validate_theme(name, raw, sizes_mm)

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
        highlight=colors[highlight_name] if highlight_name else None,
        legend_position=legend_position,
        sizes_mm=sizes_mm,
        num_thousands=raw["number_format"]["thousands"],
        num_decimal=raw["number_format"]["decimal"],
        source_prefix=raw.get("source_prefix", "Fuente:"),
    )


class ThemeError(EconchartsError):
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
    """Theme-aware y-axis tick formatter with decimals chosen from the tick spacing.

    A single fixed number of decimals breaks on small-magnitude axes (e.g. an
    exchange rate where 3.75 and 3.80 would both round to '3,8'). This reads the
    actual tick locations and uses just enough decimals to keep them distinct.
    The separators come from the theme (default es-PE: '.' thousands, ',' decimal).
    """

    def __init__(self, theme: "Theme"):
        super().__init__()
        self._theme = theme

    def set_locs(self, locs):
        steps = [abs(b - a) for a, b in zip(sorted(locs), sorted(locs)[1:]) if b != a]
        step = min(steps) if steps else 1.0
        self._decimals = 0 if step >= 1 else int(math.ceil(-math.log10(step)))

    def __call__(self, x, pos=None):
        return self._theme.format_number(x, getattr(self, "_decimals", 0))
