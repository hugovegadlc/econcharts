"""Batch document: inheritance cascade, id-based naming, selection, fail-soft."""

from __future__ import annotations

import datetime as dt

import pytest

from econcharts.batch import Batch, BatchError, run_jobs

_TODAY = dt.date(2026, 6, 11)

_BATCH = """
output_dir: out
theme: bbva
size: slides_half
charts:
  - id: a
    title: A
    period: 2021Q1:2021Q4
    series: [{name: S, type: line, data: [1, 2, 3, 4]}]
  - id: b
    title: B
    size: slides_full
    period: 2021Q1:2021Q4
    series: [{name: S, type: bar, data: [1, 2, 3, 4]}]
"""


def _batch(tmp_path, text=_BATCH, name="batch.yaml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return Batch.from_yaml(p)


def test_jobs_resolve_inheritance_and_naming(tmp_path):
    jobs = _batch(tmp_path).jobs(today=_TODAY)
    a, b = jobs
    assert [j.id for j in jobs] == ["a", "b"]
    assert a.size == "slides_half"            # inherited from header
    assert b.size == "slides_full"            # per-chart override
    assert a.body["theme"] == "bbva"          # inheritable merged into the spec body
    assert "id" not in a.body and "size" not in a.body  # orchestration keys stripped
    assert a.output_path.name == "a_20260611.png"
    assert a.output_path.parent == tmp_path / "out"     # relative to the batch file


def test_only_overrides_header_render_subset(tmp_path):
    text = _BATCH + "render: [a]\n"
    b = _batch(tmp_path, text)
    assert [j.id for j in b.jobs()] == ["a"]                  # header subset
    assert [j.id for j in b.jobs(only=["b"])] == ["b"]        # CLI --only wins


def test_duplicate_ids_rejected(tmp_path):
    text = _BATCH.replace("id: b", "id: a")
    with pytest.raises(BatchError, match="duplicate chart ids"):
        _batch(tmp_path, text)


def test_render_subset_unknown_id_rejected(tmp_path):
    with pytest.raises(BatchError, match="unknown ids"):
        _batch(tmp_path, _BATCH + "render: [nope]\n")


def test_chart_without_id_rejected(tmp_path):
    text = """
charts:
  - title: No id
    series: [{name: S, type: line, data: [1, 2]}]
"""
    with pytest.raises(BatchError, match="needs a string `id`"):
        _batch(tmp_path, text)


def test_run_jobs_is_fail_soft(tmp_path):
    text = """
output_dir: out
charts:
  - id: good
    title: G
    period: 2021Q1:2021Q4
    series: [{name: S, type: line, data: [1, 2, 3, 4]}]
  - id: bad
    title: B
    period: 2021Q1:2021Q4
    series: [{name: S, type: pie, data: [1, 2, 3, 4]}]
"""
    b = _batch(tmp_path, text)
    results = {r.id: r for r in run_jobs(b.jobs(today=_TODAY), b.resolved_data_root())}
    assert results["good"].ok and results["good"].output_path.exists()   # rendered
    assert not results["bad"].ok and results["bad"].error                # recorded, didn't crash


def test_paths_resolve_relative_to_batch_file(tmp_path):
    sub = tmp_path / "proj"
    sub.mkdir()
    b = _batch(sub)
    assert b.resolved_data_root() == sub                 # data next to the batch
    assert b.resolved_output_dir() == sub / "out"
