"""Batch documents: render many charts from one file.

A batch is a header (where data/outputs live + inheritable defaults + an optional
id subset) plus a list of chart specs, each keyed by `id`. Each chart renders to its
own figure named `<id>_<renderdate>.<backend>`. Inheritable settings resolve
theme/size/backend/date_label as: header default -> chart override.

The header is validated up front (clear errors on bad orchestration keys); each
chart's BODY is validated lazily at render time so one malformed chart can't sink the
batch (fail-soft, see `run_jobs`). Paths resolve relative to the batch FILE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from econcharts.errors import EconchartsError
from econcharts.spec import SpecError, _format_validation_error
from econcharts.theme import DEFAULT_SIZE

#: settings a chart inherits from the header unless it sets its own (the cascade).
#: theme/date_label are Spec fields (merged into the chart body); size/backend are
#: render-time and travel on the job.
_DEFAULT_BACKEND = "png"
_DEFAULT_OUTPUT_DIR = "figuras"


class BatchError(EconchartsError):
    """A batch document was malformed (header-level)."""


@dataclass
class ChartJob:
    """One chart resolved against the header: a ready-to-render unit."""

    id: str
    body: dict          # spec dict (theme/date_label inherited), minus id/size/backend
    size: str
    backend: str
    output_path: Path


@dataclass
class JobResult:
    id: str
    ok: bool
    output_path: Path
    error: Optional[str] = None


class Batch(BaseModel):
    """A batch document. `charts` stay raw dicts — validated per-chart at render."""

    model_config = ConfigDict(extra="forbid")

    data_root: Optional[str] = None
    output_dir: str = _DEFAULT_OUTPUT_DIR
    theme: Optional[str] = None
    size: Optional[str] = None
    backend: Optional[str] = None
    date_label: Optional[str] = None
    render: Optional[list[str]] = None          # id subset; None = all
    charts: list[dict[str, Any]] = Field(min_length=1)

    _base_dir: Path = PrivateAttr(default_factory=Path)

    @model_validator(mode="after")
    def _check_ids(self):
        ids = []
        for i, c in enumerate(self.charts):
            if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"]:
                raise ValueError(f"charts.{i}: each chart needs a string `id`")
            ids.append(c["id"])
        dupes = {x for x in ids if ids.count(x) > 1}
        if dupes:
            raise ValueError(f"duplicate chart ids: {', '.join(sorted(dupes))}")
        if self.render is not None:
            missing = [r for r in self.render if r not in ids]
            if missing:
                raise ValueError(f"render names unknown ids: {', '.join(missing)}")
        return self

    # -- loading --
    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "Batch":
        path = Path(path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise BatchError(f"{path}: top-level YAML must be a mapping")
        try:
            obj = cls.model_validate(raw)
        except ValidationError as e:
            raise BatchError(_format_validation_error(e, str(path))) from None
        obj._base_dir = path.resolve().parent
        return obj

    # -- path resolution (relative to the batch file) --
    def resolved_data_root(self) -> Path:
        if self.data_root:
            p = Path(self.data_root)
            return p if p.is_absolute() else self._base_dir / p
        return self._base_dir

    def resolved_output_dir(self) -> Path:
        p = Path(self.output_dir)
        return p if p.is_absolute() else self._base_dir / p

    # -- resolution to jobs --
    def jobs(self, only: Optional[list[str]] = None,
             today: Optional[date] = None) -> list[ChartJob]:
        """Resolve the selected charts into render-ready jobs. `only` (CLI) wins over
        the header `render` subset; neither given = all charts."""
        wanted = only if only is not None else self.render
        stamp = (today or date.today()).strftime("%Y%m%d")
        out_dir = self.resolved_output_dir()
        jobs = []
        for c in self.charts:
            if wanted is not None and c["id"] not in wanted:
                continue
            cid = c["id"]
            size = c.get("size") or self.size or DEFAULT_SIZE
            backend = c.get("backend") or self.backend or _DEFAULT_BACKEND
            body = {k: v for k, v in c.items() if k not in ("id", "size", "backend")}
            if "theme" not in body and self.theme is not None:
                body["theme"] = self.theme
            if "date_label" not in body and self.date_label is not None:
                body["date_label"] = self.date_label
            jobs.append(ChartJob(cid, body, size, backend,
                                 out_dir / f"{cid}_{stamp}.{backend}"))
        return jobs


def run_jobs(jobs: list[ChartJob], data_root: Union[str, Path]) -> list[JobResult]:
    """Render + save each job, FAIL-SOFT: a chart that errors is recorded (with its
    id) and the rest continue. Returns one JobResult per job."""
    import matplotlib.pyplot as plt

    from econcharts.render import render, save
    from econcharts.spec import Spec

    results: list[JobResult] = []
    for job in jobs:
        try:
            spec = Spec.from_dict(job.body, source_name=job.id)
            fig = render(spec, size=job.size, data_root=data_root)
            save(fig, job.output_path, backend=job.backend)
            plt.close(fig)
            results.append(JobResult(job.id, True, job.output_path))
        except Exception as e:  # noqa: BLE001 — fail-soft is the whole point here
            results.append(JobResult(job.id, False, job.output_path, str(e)))
    return results
