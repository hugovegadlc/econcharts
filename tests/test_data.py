"""Period parsing and the long-df resolver contract."""

from __future__ import annotations

import pandas as pd
import pytest

from econcharts.data import (
    LONG_COLUMNS,
    DataError,
    DataResolver,
    parse_period,
    parse_window,
    parse_window_spec,
)
from econcharts.spec import Series


def test_parse_period_quarter_month_year():
    assert parse_period("2018Q1") == pd.Period("2018Q1", freq="Q")
    assert parse_period("2010M03") == pd.Period("2010-03", freq="M")
    assert parse_period("2024") == pd.Period("2024", freq="Y")


def test_parse_period_daily_iso():
    p = parse_period("2024-03-15")
    assert p == pd.Period("2024-03-15", freq="D")
    assert p.freqstr == "D"


def test_infer_daily_freq_from_business_day_datetimes():
    from econcharts.data import _infer_period_freq

    bdays = pd.Series(pd.bdate_range("2024-01-01", periods=20))  # weekday gaps
    assert _infer_period_freq(bdays) == "D"


def test_parse_window_daily():
    w = parse_window("2024-03-01:2024-03-31")
    assert w.freqstr == "D" and len(w) == 31
    assert str(w[0]) == "2024-03-01" and str(w[-1]) == "2024-03-31"


def test_parse_period_rejects_garbage():
    with pytest.raises(DataError):
        parse_period("nope")


def test_parse_window_inclusive_quarterly():
    w = parse_window("2021Q1:2021Q4")
    assert isinstance(w, pd.PeriodIndex)
    assert len(w) == 4
    assert w.freqstr.startswith("Q")
    assert str(w[0]) == "2021Q1" and str(w[-1]) == "2021Q4"


def test_parse_window_single_token():
    assert len(parse_window("2024")) == 1


def test_parse_window_mismatched_freq_rejected():
    with pytest.raises(DataError):
        parse_window("2021Q1:2022M01")


def test_window_spec_end_token_is_open_until_materialized():
    spec = parse_window_spec("2021Q1:end")
    assert spec.is_open and spec.end is None and spec.start is not None
    w = spec.materialize(None, pd.Period("2022Q3", freq="Q"))  # sample's last period
    assert str(w[0]) == "2021Q1" and str(w[-1]) == "2022Q3" and len(w) == 7


def test_window_spec_start_token_resolves_from_sample_min():
    spec = parse_window_spec("start:2022Q4")
    assert spec.is_open and spec.start is None and spec.end is not None
    w = spec.materialize(pd.Period("2022Q1", freq="Q"), None)  # sample's first period
    assert str(w[0]) == "2022Q1" and str(w[-1]) == "2022Q4" and len(w) == 4


def test_window_spec_both_open_spans_the_sample():
    w = parse_window_spec("start:end").materialize(
        pd.Period("2021Q2", freq="Q"), pd.Period("2022Q1", freq="Q"))
    assert str(w[0]) == "2021Q2" and str(w[-1]) == "2022Q1"


def test_window_spec_open_token_needs_data():
    with pytest.raises(DataError, match="needs at least one dated series"):
        parse_window_spec("2021Q1:end").materialize(None, None)
    with pytest.raises(DataError, match="needs at least one dated series"):
        parse_window_spec("start:2021Q4").materialize(None, None)


def test_window_spec_open_bound_freq_must_match_data():
    with pytest.raises(DataError, match="cannot resolve"):
        parse_window_spec("2021Q1:end").materialize(None, pd.Period("2022-03", freq="M"))


def test_concrete_parse_window_still_returns_index():
    # The `end` token only makes sense with data; a concrete window stays eager.
    assert list(map(str, parse_window("2021Q1:2021Q3"))) == ["2021Q1", "2021Q2", "2021Q3"]


def test_inline_list_resolves_to_long_df():
    window = parse_window("2021Q1:2021Q4")
    df = DataResolver(window=window).resolve_series(
        Series(name="x", type="line", data=[1.0, 2.0, 3.0, 4.0])
    )
    assert list(df.columns) == LONG_COLUMNS
    assert len(df) == 4
    assert (df["series"] == "x").all()
    assert isinstance(df["period"].iloc[0], pd.Period)
    assert df["value"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_inline_list_length_must_match_window():
    window = parse_window("2021Q1:2021Q4")  # 4 points
    with pytest.raises(DataError) as e:
        DataResolver(window=window).resolve_series(
            Series(name="x", type="line", data=[1, 2, 3])  # 3 values
        )
    assert "x" in str(e.value)


def test_inline_list_without_window_rejected():
    with pytest.raises(DataError):
        DataResolver(window=None).resolve_series(Series(name="x", type="line", data=[1, 2]))


def test_inline_dict_resolves_with_own_periods():
    df = DataResolver().resolve_series(
        Series(name="x", type="line", data={"2020Q1": 1.0, "2020Q2": 2.0})
    )
    assert len(df) == 2
    assert df["value"].tolist() == [1.0, 2.0]


def test_excel_ref_is_dispatched_to_excel_backend():
    # Excel is implemented now; a bad path surfaces a clear resolver error
    # (full excel coverage lives in test_excel.py).
    with pytest.raises(DataError, match="workbook not found"):
        DataResolver().resolve_series(Series(name="x", type="line", data="excel:f.xlsx#s!c"))


def test_unknown_ref_prefix_rejected():
    with pytest.raises(DataError):
        DataResolver().resolve_series(Series(name="x", type="line", data="bogus:thing"))
