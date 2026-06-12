"""Whole-gallery batch test: assemble every example spec into one Batch and render
them all in a single run via the batch machinery — a regression guard over the full
example set (and a demo of `run_jobs` at scale)."""

from __future__ import annotations

import yaml

from conftest import EXAMPLES
from econcharts.batch import Batch, run_jobs


def _example_charts():
    """Every examples/*.yaml that is a single chart (skip batch documents), each
    turned into a batch chart entry keyed by its filename stem."""
    charts = []
    for f in sorted(EXAMPLES.glob("*.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "charts" in raw:   # skip batch docs
            continue
        raw["id"] = f.stem
        charts.append(raw)
    return charts


def test_all_examples_render_in_one_batch(tmp_path):
    charts = _example_charts()
    assert charts, "expected example specs to collect"

    batch = Batch.model_validate({"output_dir": str(tmp_path), "charts": charts})
    batch._base_dir = EXAMPLES   # excel refs resolve against examples/

    results = run_jobs(batch.jobs(), batch.resolved_data_root())

    failed = [(r.id, r.error.splitlines()[0]) for r in results if not r.ok]
    assert not failed, "examples failed to render:\n" + "\n".join(f"  {i}: {e}" for i, e in failed)
    assert len(results) == len(charts)
    for r in results:
        assert r.output_path.exists()
