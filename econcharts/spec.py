"""Pydantic v2 models for the econcharts spec, plus YAML loading.

This is the spec boundary: validation errors must surface here naming the
offending key, never as a raw matplotlib/pandas traceback downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional, Union

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

SeriesType = Literal["line", "bar", "area", "stacked"]
Axis = Literal["primary", "secondary"]
LineStyle = Literal["solid", "dashed", "dotted"]  # line series stroke override

# Annotations carry a small, fixed FORM vocabulary (resolved to real values by
# the theme) — annotations have no BBVA default to inherit, so the author needs
# limited control. Recognized annotation type keys grow per build chunk.
AnnColor = Literal["grey", "orange", "blue"]
AnnWeight = Literal["thin", "thick"]
AnnLine = Literal["solid", "dotted"]
_ANNOTATION_TYPES = {"hline", "vline", "span", "band"}  # extended in later chunks


class _LineAnn(BaseModel):
    """Shared style for line annotations."""

    model_config = ConfigDict(extra="forbid")
    color: AnnColor = "grey"
    weight: AnnWeight = "thin"
    line: AnnLine = "solid"


class HLine(_LineAnn):
    """Horizontal reference line(s) at one or more y-values (e.g. `hline: 0`)."""

    hline: Union[float, list[float]]


class VLine(_LineAnn):
    """Vertical reference line(s) at one or more period tokens (e.g. `vline: 2020Q2`)."""

    vline: Union[str, list[str]]


class _FillAnn(BaseModel):
    """Shared style for shaded-region annotations (no border; alpha is theme-set)."""

    model_config = ConfigDict(extra="forbid")
    color: AnnColor = "grey"


class SpanBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    start: str = Field(alias="from")  # 'from' is a Python keyword
    to: str
    label: Optional[str] = None


class Span(_FillAnn):
    """A shaded vertical period: `span: {from, to, label?}`."""

    span: SpanBody


class BandBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    y0: float
    y1: float
    label: Optional[str] = None


class Band(_FillAnn):
    """A shaded horizontal band: `band: {y0, y1, label?}`."""

    band: BandBody


Annotation = Union[HLine, VLine, Span, Band]

# Inline data: a plain list of numbers (hand-authorable convenience), or a
# {period: value} mapping. String forms are deferred refs (excel:/gsheet:/db:).
InlineData = Union[list[Optional[float]], dict[str, Optional[float]]]


class MarkSpec(BaseModel):
    """Per-series data-label mark: value text, plus an optional dot for lines.

    `at` is "all" | "last" | a period token | a list of tokens. `value` toggles the
    numeric label; `text` replaces it with custom text (single point only). Per-type
    rules are validated on the Series.
    """

    model_config = ConfigDict(extra="forbid")

    at: Union[str, list[str]]
    marker: bool = False  # filled dot (line series only)
    value: bool = True    # show the numeric value as a text label
    text: Optional[str] = None  # custom text that replaces the value at a single point


class Series(BaseModel):
    """One plotted series. `type` is required — there is no chart-level default."""

    model_config = ConfigDict(extra="forbid")

    name: str
    data: Union[str, InlineData]
    type: SeriesType
    axis: Axis = "primary"
    label: Optional[str] = None
    mark: Optional[MarkSpec] = None
    # Form overrides. `color` pins the series to a theme palette color by NAME (not
    # a raw hex — validated against the theme at render); `line` switches the stroke
    # (line series only). Both default to the theme's automatic choice.
    color: Optional[str] = None
    line: LineStyle = "solid"

    @property
    def legend_label(self) -> str:
        return self.label or self.name

    @field_validator("mark", mode="before")
    @classmethod
    def _coerce_mark_shorthand(cls, v):
        # mark: last  /  mark: [2020Q2, 2021Q1]  ->  {at: ...}
        if isinstance(v, (str, list)):
            return {"at": v}
        return v

    @model_validator(mode="after")
    def _validate_line_override(self):
        if self.line != "solid" and self.type != "line":
            raise ValueError(
                f"series {self.name!r}: `line` style is only for line series, not {self.type!r}"
            )
        return self

    @model_validator(mode="after")
    def _validate_mark(self):
        m = self.mark
        if m is None:
            return self
        if m.marker and self.type != "line":
            raise ValueError(
                f"series {self.name!r}: `marker` is only for line series, not {self.type!r}"
            )
        if self.type == "line" and not (m.marker or m.value or m.text is not None):
            raise ValueError(f"series {self.name!r}: a line mark needs a marker, value, or text")
        single_point = isinstance(m.at, str) and m.at != "all"
        if m.text is not None and not single_point:
            raise ValueError(
                f"series {self.name!r}: mark `text` requires a single point (last or one date)"
            )
        return self


class Spec(BaseModel):
    """A full chart declaration."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    subtitle: Optional[str] = None
    source: Optional[str] = None
    period: Optional[str] = None
    theme: str = "bbva"
    ylabel: Optional[str] = None
    y2label: Optional[str] = None
    # Selects a theme date-label style by NAME (e.g. `quarter`/`month`, `plain`/
    # `dotted`), applied per granularity where defined; default = the theme's.
    date_label: Optional[str] = None

    series: list[Series] = Field(min_length=1)
    annotations: list[Annotation] = Field(default_factory=list)
    # Escape hatch: raw rcParam / axis overrides. Rarely touched.
    style: dict[str, Any] = Field(default_factory=dict)

    @field_validator("annotations", mode="before")
    @classmethod
    def _recognize_annotations(cls, v):
        """Surface a clear error for an unknown annotation type before the union
        validator emits a noisy "no member matched" message."""
        if not isinstance(v, list):
            return v
        for i, item in enumerate(v):
            if not isinstance(item, dict):
                raise ValueError(f"annotations.{i}: must be a mapping, got {type(item).__name__}")
            present = _ANNOTATION_TYPES & item.keys()
            if not present:
                raise ValueError(
                    f"annotations.{i}: unknown annotation; expected one of {sorted(_ANNOTATION_TYPES)}"
                )
            if len(present) > 1:
                raise ValueError(f"annotations.{i}: more than one type key {sorted(present)}")
        return v

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "Spec":
        """Load and validate a spec from a YAML file."""
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SpecError(f"{path}: top-level YAML must be a mapping, got {type(raw).__name__}")
        return cls.from_dict(raw, source_name=str(path))

    @classmethod
    def from_dict(cls, raw: dict[str, Any], source_name: str = "<spec>") -> "Spec":
        try:
            return cls.model_validate(raw)
        except ValidationError as e:
            raise SpecError(_format_validation_error(e, source_name)) from None


class SpecError(ValueError):
    """A spec failed validation. Message names the offending key(s)."""


def _format_validation_error(e: ValidationError, source_name: str) -> str:
    lines = [f"Invalid spec ({source_name}):"]
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
