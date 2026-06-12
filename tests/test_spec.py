"""Schema boundary: valid specs parse, malformed ones raise at the right key."""

from __future__ import annotations

import pytest

from econcharts.spec import Series, Spec, SpecError


def _minimal(**over):
    base = {"title": "T", "series": [{"name": "A", "type": "line", "data": [1, 2, 3]}]}
    base.update(over)
    return base


def test_title_is_optional():
    spec = Spec.from_dict({"series": [{"name": "A", "type": "line", "data": [1, 2]}]})
    assert spec.title is None
    assert spec.subtitle is None


def test_minimal_spec_parses():
    spec = Spec.from_dict(_minimal())
    assert spec.title == "T"
    assert spec.theme == "bbva"  # default
    assert len(spec.series) == 1
    assert spec.series[0].axis == "primary"  # default


def test_series_type_is_required():
    bad = {"title": "T", "series": [{"name": "A", "data": [1, 2]}]}
    with pytest.raises(SpecError) as e:
        Spec.from_dict(bad)
    assert "series.0.type" in str(e.value)


def test_empty_series_list_rejected():
    with pytest.raises(SpecError) as e:
        Spec.from_dict({"title": "T", "series": []})
    assert "series" in str(e.value)


def test_all_four_types_accepted():
    for t in ("line", "bar", "area", "stacked"):
        spec = Spec.from_dict(_minimal(series=[{"name": "A", "type": t, "data": [1, 2]}]))
        assert spec.series[0].type == t


def test_unknown_series_type_rejected():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(series=[{"name": "A", "type": "bubble", "data": [1]}]))
    assert "series.0.type" in str(e.value)


def test_unknown_axis_rejected():
    bad = _minimal(series=[{"name": "A", "type": "line", "data": [1], "axis": "tertiary"}])
    with pytest.raises(SpecError) as e:
        Spec.from_dict(bad)
    assert "series.0.axis" in str(e.value)


def test_extra_top_level_key_forbidden():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(colour="blue"))
    assert "colour" in str(e.value)


def test_extra_series_key_forbidden():
    bad = _minimal(series=[{"name": "A", "type": "line", "data": [1], "wibble": 1}])
    with pytest.raises(SpecError) as e:
        Spec.from_dict(bad)
    assert "wibble" in str(e.value)


def test_legend_label_falls_back_to_name():
    assert Series(name="PBI", type="line", data=[1]).legend_label == "PBI"
    assert Series(name="PBI", type="line", data=[1], label="Producto").legend_label == "Producto"


def test_hline_annotation_parses_with_defaults():
    spec = Spec.from_dict(_minimal(annotations=[{"hline": 0}]))
    ann = spec.annotations[0]
    assert ann.hline == 0
    assert (ann.color, ann.weight, ann.line) == ("grey", "thin", "solid")


def test_styled_vline_annotation_parses():
    spec = Spec.from_dict(_minimal(
        annotations=[{"vline": "2020Q2", "color": "blue", "weight": "thick", "line": "dotted"}]))
    ann = spec.annotations[0]
    assert ann.vline == "2020Q2"
    assert (ann.color, ann.weight, ann.line) == ("blue", "thick", "dotted")


def test_unknown_annotation_type_rejected():
    with pytest.raises(SpecError, match="unknown annotation"):
        Spec.from_dict(_minimal(annotations=[{"recessions": "peru"}]))


def test_bad_annotation_color_rejected():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(annotations=[{"hline": 0, "color": "magenta"}]))
    assert "color" in str(e.value)


def test_hline_value_must_be_numeric():
    with pytest.raises(SpecError):
        Spec.from_dict(_minimal(annotations=[{"hline": "abc"}]))


def test_extra_annotation_key_forbidden():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(annotations=[{"hline": 0, "wibble": 1}]))
    assert "wibble" in str(e.value)


def test_span_parses_with_from_alias():
    spec = Spec.from_dict(_minimal(annotations=[{"span": {"from": "2020Q1", "to": "2020Q4"}}]))
    ann = spec.annotations[0]
    assert ann.span.start == "2020Q1" and ann.span.to == "2020Q4"
    assert ann.color == "grey"  # default fill color


def test_band_parses():
    spec = Spec.from_dict(_minimal(
        annotations=[{"band": {"y0": 1, "y1": 3, "label": "Meta"}, "color": "blue"}]))
    ann = spec.annotations[0]
    assert (ann.band.y0, ann.band.y1, ann.band.label) == (1, 3, "Meta")
    assert ann.color == "blue"


def test_span_missing_to_rejected():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(annotations=[{"span": {"from": "2020Q1"}}]))
    assert "to" in str(e.value)


def test_band_y_must_be_numeric():
    with pytest.raises(SpecError):
        Spec.from_dict(_minimal(annotations=[{"band": {"y0": "x", "y1": 3}}]))


def test_mark_shorthand_coerces_to_at():
    spec = Spec.from_dict(_minimal(series=[{"name": "A", "type": "line", "data": [1, 2], "mark": "last"}]))
    m = spec.series[0].mark
    assert m.at == "last" and m.value is True and m.marker is False


def test_mark_mapping_parses():
    spec = Spec.from_dict(_minimal(series=[
        {"name": "A", "type": "line", "data": [1, 2], "mark": {"at": "all", "marker": True}}]))
    assert spec.series[0].mark.at == "all" and spec.series[0].mark.marker is True


def test_marker_on_non_line_rejected():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(series=[
            {"name": "A", "type": "bar", "data": [1, 2], "mark": {"at": "all", "marker": True}}]))
    assert "marker" in str(e.value)


def test_line_mark_needs_marker_value_or_text():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(series=[
            {"name": "A", "type": "line", "data": [1, 2],
             "mark": {"at": "last", "marker": False, "value": False}}]))
    assert "marker, value, or text" in str(e.value)


def test_mark_text_requires_single_point():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(series=[
            {"name": "A", "type": "line", "data": [1, 2], "mark": {"at": "all", "text": "x"}}]))
    assert "single point" in str(e.value)


def test_mark_text_on_single_point_ok():
    spec = Spec.from_dict(_minimal(series=[
        {"name": "A", "type": "line", "data": [1, 2], "mark": {"at": "last", "text": "COVID"}}]))
    assert spec.series[0].mark.text == "COVID"


def test_example_yaml_loads(example_spec):
    assert example_spec.title == "Inflación — Perú"
    assert example_spec.period == "2021Q1:2024Q4"
    assert [s.name for s in example_spec.series] == ["Inflación total", "Inflación subyacente"]
    assert example_spec.source == "BCRP"  # parsed as metadata even though not drawn


def test_highlight_shorthand_coerces_to_at():
    spec = Spec.from_dict(_minimal(series=[
        {"name": "A", "type": "bar", "data": [1, 2], "highlight": "last"}]))
    assert spec.series[0].highlight.at == "last"
    assert spec.series[0].highlight.color is None


def test_highlight_mapping_parses():
    spec = Spec.from_dict(_minimal(series=[
        {"name": "A", "type": "bar", "data": [1, 2],
         "highlight": {"at": ["2026", "2027"], "color": "blue"}}]))
    assert spec.series[0].highlight.at == ["2026", "2027"]
    assert spec.series[0].highlight.color == "blue"


def test_highlight_on_non_bar_rejected():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(series=[
            {"name": "A", "type": "line", "data": [1, 2], "highlight": "last"}]))
    assert "only for bar series" in str(e.value)


def test_highlight_at_all_rejected():
    with pytest.raises(SpecError) as e:
        Spec.from_dict(_minimal(series=[
            {"name": "A", "type": "bar", "data": [1, 2], "highlight": "all"}]))
    assert "use `color` instead" in str(e.value)
