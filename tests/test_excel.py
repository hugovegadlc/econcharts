"""Excel resolver: ref parsing, period coercion, DATA_ROOT, errors, end-to-end.

Workbooks are built in tmp_path so nothing binary is committed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from econcharts import render
from econcharts.data import DataResolver, DataError, parse_window
from econcharts.spec import Series, Spec


@pytest.fixture
def workbook(tmp_path):
    """A workbook with three sheets exercising each period-column flavor."""
    path = tmp_path / "datos.xlsx"
    tokens = pd.DataFrame({
        "periodo": ["2021Q1", "2021Q2", "2021Q3", "2021Q4"],
        "total": [2.4, 2.6, 4.2, 6.4],
        "subyacente": [1.8, 2.0, 2.6, 3.2],
    })
    dates = pd.DataFrame({
        "fecha": pd.period_range("2020Q1", "2020Q4", freq="Q").to_timestamp(),
        "pbi": [1.0, 2.0, 3.0, 4.0],
    })
    annual = pd.DataFrame({"anio": [2018, 2019, 2020, 2021], "x": [10, 11, 12, 13]})
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        tokens.to_excel(xw, sheet_name="trim", index=False)
        dates.to_excel(xw, sheet_name="fechas", index=False)
        annual.to_excel(xw, sheet_name="anual", index=False)
    return path


def _resolve(tmp_root, ref, name="s", **kw):
    return DataResolver(data_root=tmp_root, **kw).resolve_series(
        Series(name=name, type="line", data=ref)
    )


def test_token_period_column(workbook):
    df = _resolve(workbook.parent, "excel:datos.xlsx#trim!total")
    assert list(df.columns) == ["period", "series", "value"]
    assert [str(p) for p in df["period"]] == ["2021Q1", "2021Q2", "2021Q3", "2021Q4"]
    assert df["value"].tolist() == [2.4, 2.6, 4.2, 6.4]


def test_datetime_period_column_infers_quarterly(workbook):
    df = _resolve(workbook.parent, "excel:datos.xlsx#fechas!pbi")
    assert all(p.freqstr.startswith("Q") for p in df["period"])
    assert [str(p) for p in df["period"]] == ["2020Q1", "2020Q2", "2020Q3", "2020Q4"]


def test_year_integer_period_column_is_annual(workbook):
    df = _resolve(workbook.parent, "excel:datos.xlsx#anual!x")
    assert all(p.freqstr.startswith(("A", "Y")) for p in df["period"])
    assert [p.year for p in df["period"]] == [2018, 2019, 2020, 2021]


def test_window_clips_excel_rows(workbook):
    df = DataResolver(
        data_root=workbook.parent, window=parse_window("2021Q2:2021Q3")
    ).resolve_series(Series(name="s", type="line", data="excel:datos.xlsx#trim!total"))
    assert [str(p) for p in df["period"]] == ["2021Q2", "2021Q3"]


def test_absolute_path_resolves_without_data_root(workbook):
    ref = f"excel:{workbook}#trim!subyacente"
    df = DataResolver().resolve_series(Series(name="s", type="line", data=ref))
    assert df["value"].tolist() == [1.8, 2.0, 2.6, 3.2]


def test_data_root_from_env(workbook, monkeypatch):
    monkeypatch.setenv("ECONCHARTS_DATA_ROOT", str(workbook.parent))
    df = DataResolver().resolve_series(Series(name="s", type="line", data="excel:datos.xlsx#trim!total"))
    assert len(df) == 4


def test_sheets_are_cached(workbook):
    r = DataResolver(data_root=workbook.parent)
    r.resolve_series(Series(name="a", type="line", data="excel:datos.xlsx#trim!total"))
    r.resolve_series(Series(name="b", type="line", data="excel:datos.xlsx#trim!subyacente"))
    assert len(r._sheet_cache) == 1  # one sheet read, reused


def test_missing_workbook_errors(tmp_path):
    with pytest.raises(DataError, match="workbook not found"):
        _resolve(tmp_path, "excel:nope.xlsx#trim!total")


def test_missing_sheet_errors(workbook):
    with pytest.raises(DataError, match="sheet 'nope' not found"):
        _resolve(workbook.parent, "excel:datos.xlsx#nope!total")


def test_missing_column_lists_available(workbook):
    with pytest.raises(DataError) as e:
        _resolve(workbook.parent, "excel:datos.xlsx#trim!nope")
    msg = str(e.value)
    assert "column 'nope' not in sheet" in msg
    assert "total" in msg and "subyacente" in msg  # available columns listed


def test_malformed_excel_ref_errors(workbook):
    with pytest.raises(DataError, match="malformed excel ref"):
        _resolve(workbook.parent, "excel:datos.xlsx")


def test_end_to_end_render_from_excel(workbook):
    spec = Spec.from_dict({
        "title": "Inflación — Perú",
        "subtitle": "var. % anual",
        "period": "2021Q1:2021Q4",
        "series": [
            {"name": "Inflación total", "type": "line", "data": "excel:datos.xlsx#trim!total"},
            {"name": "Subyacente", "type": "line", "data": "excel:datos.xlsx#trim!subyacente"},
        ],
    })
    fig = render(spec, data_root=workbook.parent)
    assert len(fig.axes[0].get_lines()) == 2


def test_inline_and_excel_coexist_in_one_spec(workbook):
    """Inline data is still first-class alongside excel refs."""
    spec = Spec.from_dict({
        "title": "mix",
        "period": "2021Q1:2021Q4",
        "series": [
            {"name": "from_excel", "type": "line", "data": "excel:datos.xlsx#trim!total"},
            {"name": "from_inline", "type": "line", "data": [1.0, 2.0, 3.0, 4.0]},
        ],
    })
    df = DataResolver(data_root=workbook.parent, window=parse_window(spec.period)).resolve(spec)
    assert set(df["series"]) == {"from_excel", "from_inline"}
    assert len(df) == 8
