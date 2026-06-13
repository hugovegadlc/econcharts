"""Theme: palette extraction, named export sizes, es-PE formatters."""

from __future__ import annotations

import pandas as pd
import pytest

from econcharts.theme import (
    DEFAULT_SIZE,
    SIZES_MM,
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


@pytest.mark.parametrize("name,mm", SIZES_MM.items())
def test_figsize_matches_mm(name, mm):
    from econcharts.theme import Theme

    w_in, h_in = Theme.figsize(name)
    assert w_in == pytest.approx(mm[0] / 25.4)
    assert h_in == pytest.approx(mm[1] / 25.4)


def test_unknown_size_errors():
    from econcharts.theme import Theme

    with pytest.raises(ThemeError):
        Theme.figsize("billboard")


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
    f = EsPeNumber()
    f.set_locs([3.70, 3.75, 3.80, 3.85])  # 0.05 spacing -> 2 decimals, all distinct
    labels = [f(v) for v in (3.70, 3.75, 3.80)]
    assert labels == ["3,70", "3,75", "3,80"]
    f.set_locs([0, 2, 4, 6])              # integer spacing -> no decimals
    assert f(4) == "4"


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
