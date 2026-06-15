"""Theme: palette extraction, named export sizes, es-PE formatters."""

from __future__ import annotations

import pandas as pd
import pytest

from econcharts.theme import (
    DEFAULT_SIZE,
    EsPeNumber,
    ThemeError,
    es_pe,
    format_period,
    load_theme,
)


def test_bbva_palette_is_2025_primary():
    theme = load_theme("bbva")
    assert theme.palette[0].lower() == "#001391"  # 2025 primary, not classic #004481
    assert theme.color(0).lower() == "#001391"
    # structural grey #cad1d8 is reserved (gridlines), not in the series cycle
    assert "#cad1d8" not in [c.lower() for c in theme.palette]


def test_palette_cycles():
    theme = load_theme("bbva")
    n = len(theme.palette)
    assert theme.color(n) == theme.color(0)


def test_unknown_theme_errors():
    with pytest.raises(ThemeError):
        load_theme("does-not-exist")


def test_date_label_styles_per_granularity():
    t = load_theme("bbva")
    q = pd.Period("2024Q1", freq="Q")
    assert t.date_label(q, "Q") == "mar-24"               # default: month (closing month)
    assert t.date_label(q, "Q", "quarter") == "1T24"
    assert t.date_label(q, "Y") == "2024"                 # coarsen Q->Y
    m = pd.Period("2024-03", freq="M")
    assert t.date_label(m, "M") == "mar-24"               # default: plain
    assert t.date_label(m, "M", "dotted") == "mar.-24"
    d = pd.Period("2024-07-15", freq="D")
    assert t.date_label(d, "D") == "15-jul"               # default: plain
    assert t.date_label(d, "D", "dotted") == "15-jul."
    assert t.date_label(d, "M") == "jul-24"               # coarsen D->M
    assert t.date_label(d, "Q") == "set-24"               # D->Q3, default month -> set (es-PE)
    assert t.date_label(d, "Q", "quarter") == "3T24"


def test_date_label_unknown_style_errors():
    with pytest.raises(ThemeError, match="unknown date-label style"):
        load_theme("bbva").date_label(pd.Period("2024Q1", freq="Q"), "Q", "nope")


def test_default_size_is_slides_half():
    assert DEFAULT_SIZE == "slides_half"


@pytest.mark.parametrize("name,mm", load_theme("bbva").sizes_mm.items())
def test_figsize_matches_mm(name, mm):
    theme = load_theme("bbva")
    w_in, h_in = theme.figsize(name)
    assert w_in == pytest.approx(mm[0] / 25.4)
    assert h_in == pytest.approx(mm[1] / 25.4)


def test_unknown_size_errors():
    with pytest.raises(ThemeError):
        load_theme("bbva").figsize("billboard")


def test_theme_sizes_override_globals():
    theme = load_theme("macro")
    w_in, h_in = theme.figsize("slides_full")
    assert w_in == pytest.approx(200 / 25.4)
    assert h_in == pytest.approx(150 / 25.4)


def test_theme_sizes_undeclared_size_errors():
    theme = load_theme("macro")
    with pytest.raises(ThemeError, match="unknown size"):
        theme.figsize("word_half")   # macro declares only slides_half/slides_full


def test_quarter_label_is_qTyy():
    assert format_period(pd.Period("2024Q1", freq="Q")) == "1T24"
    assert format_period(pd.Period("2021Q3", freq="Q")) == "3T21"


def test_annual_label():
    assert format_period(pd.Period("2024", freq="Y")) == "2024"


def test_es_pe_separator():
    assert es_pe(1234567) == "1.234.567"
    assert es_pe(50) == "50"
    assert es_pe(3.75, 2) == "3,75"
    assert es_pe(-1234.5, 1) == "-1.234,5"


def test_es_pe_value_minimal_decimals():
    from econcharts.theme import es_pe_value

    assert es_pe_value(76.0) == "76"
    assert es_pe_value(2.0) == "2"
    assert es_pe_value(3.8) == "3,8"
    assert es_pe_value(3.85) == "3,85"
    assert es_pe_value(-0.6) == "-0,6"


def test_formatter_adapts_decimals_to_tick_spacing():
    f = EsPeNumber(load_theme("bbva"))
    f.set_locs([3.70, 3.75, 3.80, 3.85])  # 0.05 spacing -> 2 decimals, all distinct
    labels = [f(v) for v in (3.70, 3.75, 3.80)]
    assert labels == ["3,70", "3,75", "3,80"]
    f.set_locs([0, 2, 4, 6])              # integer spacing -> no decimals
    assert f(4) == "4"


def test_format_number_es_pe():
    theme = load_theme("bbva")
    assert theme.format_number(1234567) == "1 234 567"
    assert theme.format_number(3.75, 2) == "3,75"
    assert theme.format_number(-1234.5, 1) == "-1 234,5"


def test_format_number_respects_theme_separators(tmp_path, monkeypatch):
    import yaml
    import econcharts.theme as theme_mod

    base = yaml.safe_load(
        (theme_mod._THEMES_DIR / "bbva.yaml").read_text(encoding="utf-8")
    )
    base["number_format"] = {"thousands": ",", "decimal": "."}
    (tmp_path / "en.yaml").write_text(yaml.dump(base), encoding="utf-8")
    monkeypatch.setattr(theme_mod, "_THEMES_DIR", tmp_path)
    theme = load_theme("en")
    assert theme.format_number(1234567) == "1,234,567"
    assert theme.format_number(3.75, 2) == "3.75"


def test_legend_position_defaults_below_and_macro_is_inside():
    assert load_theme("bbva").legend_position == "below"
    assert load_theme("macro").legend_position == "top-left"


def test_unknown_legend_position_errors(tmp_path, monkeypatch):
    import econcharts.theme as theme_mod

    (tmp_path / "bad.yaml").write_text(
        "colors: {blue: '#001391'}\ncycle: [blue]\nlegend: {position: floating}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(theme_mod, "_THEMES_DIR", tmp_path)
    with pytest.raises(ThemeError, match="unknown legend position 'floating'"):
        load_theme("bad")


# ---------------------------------------------------------------------------
# Structural validation (_validate_theme) — tested directly, no file I/O
# ---------------------------------------------------------------------------

from econcharts.theme import _validate_theme  # noqa: E402  (after class defs)

_ANN = {
    "line":    {"grey": "grey", "orange": "orange", "blue": "blue"},
    "fill":    {"grey": "grey", "orange": "orange", "blue": "blue"},
    "label":   {"grey": "grey", "orange": "orange", "blue": "blue"},
    "weights": {"thin": 1.0, "thick": 2.0},
    "lines":   {"solid": "-", "dotted": ":"},
}
_DL = {
    "D": {"options": {"plain": "{d}-{mmm}"},  "default": "plain"},
    "M": {"options": {"plain": "{mmm}-{yy}"}, "default": "plain"},
    "Q": {"options": {"month": "{mmm}-{yy}"}, "default": "month"},
    "Y": {"options": {"full": "{yyyy}"},       "default": "full"},
}
_NF = {"thousands": ".", "decimal": ","}
_MINIMAL_RAW = {"annotations": _ANN, "date_labels": _DL, "number_format": _NF}
_MINIMAL_SIZES = {"slides_half": (85, 70)}


def test_validate_passes_for_complete_theme():
    _validate_theme("t", _MINIMAL_RAW, _MINIMAL_SIZES)


def test_validate_empty_sizes_errors():
    with pytest.raises(ThemeError, match="sizes"):
        _validate_theme("t", _MINIMAL_RAW, {})


def test_validate_missing_annotations_errors():
    raw = {k: v for k, v in _MINIMAL_RAW.items() if k != "annotations"}
    with pytest.raises(ThemeError, match="annotations"):
        _validate_theme("t", raw, _MINIMAL_SIZES)


@pytest.mark.parametrize("sub", ["line", "fill", "label", "weights", "lines"])
def test_validate_missing_annotation_sub_errors(sub):
    ann = {k: v for k, v in _ANN.items() if k != sub}
    with pytest.raises(ThemeError, match=sub):
        _validate_theme("t", {**_MINIMAL_RAW, "annotations": ann}, _MINIMAL_SIZES)


def test_validate_annotation_missing_role_errors():
    ann = {**_ANN, "line": {"grey": "grey", "orange": "orange"}}   # blue missing
    with pytest.raises(ThemeError, match="blue"):
        _validate_theme("t", {**_MINIMAL_RAW, "annotations": ann}, _MINIMAL_SIZES)


def test_validate_annotation_missing_weight_errors():
    ann = {**_ANN, "weights": {"thin": 1.0}}                       # thick missing
    with pytest.raises(ThemeError, match="thick"):
        _validate_theme("t", {**_MINIMAL_RAW, "annotations": ann}, _MINIMAL_SIZES)


def test_validate_missing_date_labels_errors():
    raw = {k: v for k, v in _MINIMAL_RAW.items() if k != "date_labels"}
    with pytest.raises(ThemeError, match="date_labels"):
        _validate_theme("t", raw, _MINIMAL_SIZES)


@pytest.mark.parametrize("gran", ["D", "M", "Q", "Y"])
def test_validate_missing_granularity_errors(gran):
    dl = {k: v for k, v in _DL.items() if k != gran}
    with pytest.raises(ThemeError, match=gran):
        _validate_theme("t", {**_MINIMAL_RAW, "date_labels": dl}, _MINIMAL_SIZES)


def test_validate_bad_date_label_default_errors():
    dl = {**_DL, "Q": {"options": {"month": "{mmm}-{yy}"}, "default": "typo"}}
    with pytest.raises(ThemeError, match="default"):
        _validate_theme("t", {**_MINIMAL_RAW, "date_labels": dl}, _MINIMAL_SIZES)


def test_validate_empty_date_label_options_errors():
    dl = {**_DL, "Q": {"options": {}, "default": "month"}}
    with pytest.raises(ThemeError, match="options"):
        _validate_theme("t", {**_MINIMAL_RAW, "date_labels": dl}, _MINIMAL_SIZES)


def test_validate_missing_number_format_errors():
    raw = {k: v for k, v in _MINIMAL_RAW.items() if k != "number_format"}
    with pytest.raises(ThemeError, match="number_format"):
        _validate_theme("t", raw, _MINIMAL_SIZES)


@pytest.mark.parametrize("key", ["thousands", "decimal"])
def test_validate_missing_number_format_key_errors(key):
    nf = {k: v for k, v in _NF.items() if k != key}
    with pytest.raises(ThemeError, match=key):
        _validate_theme("t", {**_MINIMAL_RAW, "number_format": nf}, _MINIMAL_SIZES)


# cycle validation (tested via load_theme with tmp yaml files)

def test_missing_cycle_errors(tmp_path, monkeypatch):
    import econcharts.theme as theme_mod
    (tmp_path / "t.yaml").write_text(
        "colors: {blue: '#0000FF'}\nsizes: {slides_half: [85, 70]}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(theme_mod, "_THEMES_DIR", tmp_path)
    with pytest.raises(ThemeError, match="cycle"):
        load_theme("t")


def test_empty_cycle_errors(tmp_path, monkeypatch):
    import econcharts.theme as theme_mod
    (tmp_path / "t.yaml").write_text(
        "colors: {blue: '#0000FF'}\ncycle: []\nsizes: {slides_half: [85, 70]}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(theme_mod, "_THEMES_DIR", tmp_path)
    with pytest.raises(ThemeError, match="cycle"):
        load_theme("t")
