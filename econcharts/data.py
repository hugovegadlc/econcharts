"""Data resolution.

The resolver contract is fixed: it ALWAYS returns a tidy/long DataFrame with
columns [period, series, value], where `period` holds pandas Period objects of
a single explicit freq. Wide->long normalization happens here, once, at the
boundary.

v1 implements:
  - inline data (list or {period: value} mapping) — hand-authorable, always
    available regardless of which ref backends exist.
  - `excel:<file>#<sheet>!<column>` — the period column defaults to the sheet's
    first column (configurable); other columns are named series. Workbook paths
    resolve against DATA_ROOT.
gsheet:/db: refs are recognized but not yet implemented.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

import pandas as pd

from econcharts.errors import EconchartsError

if TYPE_CHECKING:
    from econcharts.spec import Series, Spec

LONG_COLUMNS = ["period", "series", "value"]

_DAILY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")        # ISO date: 2024-03-15
_QUARTER = re.compile(r"^(\d{4})Q([1-4])$", re.IGNORECASE)
_MONTH = re.compile(r"^(\d{4})M(\d{2})$", re.IGNORECASE)
_ANNUAL = re.compile(r"^(\d{4})$")

# excel:<file>#<sheet>!<column>  — file may contain spaces/backslashes.
_EXCEL_REF = re.compile(r"^excel:(?P<file>[^#]+)#(?P<sheet>[^!]+)!(?P<column>.+)$")

#: Environment variable holding the root that relative workbook paths resolve against.
DATA_ROOT_ENV = "ECONCHARTS_DATA_ROOT"


class DataError(EconchartsError):
    """A data ref or inline payload could not be resolved."""


# --- period parsing ----------------------------------------------------------

def parse_period(token: str) -> pd.Period:
    """Parse a single period token to a pd.Period.

    Daily is ISO `2024-03-15`; quarter `2018Q1`; month `2010M03`; year `2024`.
    """
    token = token.strip()
    if m := _DAILY.match(token):
        return pd.Period(year=int(m[1]), month=int(m[2]), day=int(m[3]), freq="D")
    if m := _QUARTER.match(token):
        return pd.Period(year=int(m[1]), quarter=int(m[2]), freq="Q")
    if m := _MONTH.match(token):
        return pd.Period(year=int(m[1]), month=int(m[2]), freq="M")
    if m := _ANNUAL.match(token):
        return pd.Period(year=int(m[1]), freq="Y")
    raise DataError(
        f"unrecognized period token {token!r} (expected e.g. 2024-03-15, 2018Q1, 2010M03, 2024)"
    )


# A `period:` bound may be a literal data-driven token instead of a date: `start`
# = the FIRST period of the sample, `end` = the LAST. Both are filled from the data
# once it's read (the sample's min/max across all dated series, which can differ
# from any one series' first/last point). Case-insensitive.
_OPEN_TOKENS = {"start", "end"}


def _parse_bound(token: str) -> Optional[pd.Period]:
    """A window bound: a concrete period, or None for the `start`/`end` tokens."""
    return None if token.strip().lower() in _OPEN_TOKENS else parse_period(token)


@dataclass(frozen=True)
class WindowSpec:
    """A parsed `period:` window. A None bound came from a `start`/`end` token and
    is resolved against the data's extent by `materialize`."""

    start: Optional[pd.Period]   # None => data-driven sample start
    end: Optional[pd.Period]     # None => data-driven sample end

    @property
    def is_open(self) -> bool:
        return self.start is None or self.end is None

    def materialize(
        self, sample_min: Optional[pd.Period], sample_max: Optional[pd.Period]
    ) -> pd.PeriodIndex:
        """Build the inclusive PeriodIndex, filling open bounds from the sample's
        first/last period (`sample_min`/`sample_max`)."""
        start = self.start if self.start is not None else sample_min
        end = self.end if self.end is not None else sample_max
        if start is None or end is None:
            raise DataError(
                "period `start`/`end` token needs at least one dated series (excel ref "
                "or {period: value} map) to resolve the sample's extent"
            )
        if start.freqstr != end.freqstr:
            raise DataError(
                f"period freq {start.freqstr} vs {end.freqstr}; cannot resolve window "
                f"(a data-driven bound must match the data's freq)"
            )
        if end < start:
            raise DataError(f"period end {end} precedes start {start}")
        return pd.period_range(start=start, end=end, freq=start.freqstr)


def parse_window_spec(period: str) -> WindowSpec:
    """Parse `start:end` (or a single token) into a WindowSpec. Either bound may be
    the literal `start`/`end` token (resolved later from the data)."""
    parts = period.split(":")
    if len(parts) == 1:
        start = parse_period(parts[0])
        return WindowSpec(start, start)
    if len(parts) != 2:
        raise DataError(f"period {period!r} must be 'start:end' or a single token")
    start, end = _parse_bound(parts[0]), _parse_bound(parts[1])
    if start is not None and end is not None and start.freqstr != end.freqstr:
        raise DataError(f"period bounds have mismatched freq: {start.freqstr} vs {end.freqstr}")
    return WindowSpec(start, end)


def parse_window(period: str) -> pd.PeriodIndex:
    """Parse `start:end` (or a single token) into an inclusive PeriodIndex.

    Convenience for callers with a fully-concrete window; using a `start`/`end`
    token here raises (it needs the data — go via `parse_window_spec` + `materialize`).
    """
    return parse_window_spec(period).materialize(None, None)


def clip_to_window(df: pd.DataFrame, window: Optional[pd.PeriodIndex]) -> pd.DataFrame:
    """Drop rows whose period falls outside `window` (inclusive). No-op if no window."""
    if window is None or df.empty:
        return df
    data_freq = df["period"].iloc[0].freqstr[0]
    win_freq = window[0].freqstr[0]
    if data_freq != win_freq:
        raise DataError(
            f"period window freq ({win_freq}) doesn't match data freq ({data_freq}); "
            f"the `period` key must use the same granularity as the data"
        )
    lo, hi = window[0], window[-1]
    keep = [lo <= p <= hi for p in df["period"]]
    return df[keep].reset_index(drop=True)


# --- resolver ----------------------------------------------------------------

class DataResolver:
    """Resolves series data refs to the long-df contract.

    `data_root` is where relative workbook paths resolve (defaults to the
    ``ECONCHARTS_DATA_ROOT`` env var, else the current directory). `period_col`
    overrides the sheet column used as the period axis (default: first column).
    """

    def __init__(
        self,
        window: Optional[pd.PeriodIndex] = None,
        data_root: Optional[Union[str, Path]] = None,
        period_col: Optional[Union[str, int]] = None,
    ):
        self.window = window
        if data_root is None:
            data_root = os.environ.get(DATA_ROOT_ENV)
        self.data_root = Path(data_root) if data_root else None
        self.period_col = period_col
        self._sheet_cache: dict[tuple[str, str], pd.DataFrame] = {}

    def resolve_series(self, series: "Series") -> pd.DataFrame:
        data = series.data
        if isinstance(data, str):
            return self._resolve_ref(series.name, data)
        return self._resolve_inline(series.name, data)

    def resolve(self, spec: "Spec") -> pd.DataFrame:
        """Resolve every series in a spec into one concatenated long df."""
        frames = [self.resolve_series(s) for s in spec.series]
        return pd.concat(frames, ignore_index=True)

    # -- inline --
    def _resolve_inline(self, name: str, data) -> pd.DataFrame:
        if isinstance(data, dict):
            periods = [parse_period(k) for k in data]
            values = list(data.values())
        elif isinstance(data, list):
            if self.window is None:
                raise DataError(
                    f"series {name!r}: inline list data needs a chart-level `period` window to align to"
                )
            if len(data) != len(self.window):
                raise DataError(
                    f"series {name!r}: {len(data)} inline values but period window has "
                    f"{len(self.window)} points"
                )
            periods = list(self.window)
            values = list(data)
        else:
            raise DataError(f"series {name!r}: unsupported inline data type {type(data).__name__}")
        return pd.DataFrame({"period": periods, "series": name, "value": values})[LONG_COLUMNS]

    def _clip_window(self, df: pd.DataFrame) -> pd.DataFrame:
        return clip_to_window(df, self.window)

    # -- refs --
    def _resolve_ref(self, name: str, ref: str) -> pd.DataFrame:
        prefix = ref.split(":", 1)[0] if ":" in ref else ""
        if prefix == "excel":
            return self._resolve_excel(name, ref)
        if prefix in ("gsheet", "db"):
            raise DataError(f"series {name!r}: {prefix}: resolver is not implemented yet")
        raise DataError(f"series {name!r}: unrecognized data ref {ref!r}")

    # -- excel --
    def _resolve_excel(self, name: str, ref: str) -> pd.DataFrame:
        m = _EXCEL_REF.match(ref)
        if not m:
            raise DataError(
                f"series {name!r}: malformed excel ref {ref!r}; "
                f"expected excel:<file>#<sheet>!<column>"
            )
        file, sheet, column = m["file"].strip(), m["sheet"].strip(), m["column"].strip()
        df = self._read_sheet(name, file, sheet)

        pcol = df.columns[0] if self.period_col is None else self.period_col
        if isinstance(pcol, int):
            if pcol >= len(df.columns):
                raise DataError(f"series {name!r}: period column index {pcol} out of range in {sheet!r}")
            pcol = df.columns[pcol]
        elif pcol not in df.columns:
            raise DataError(f"series {name!r}: period column {pcol!r} not in sheet {sheet!r}")
        if column not in df.columns:
            avail = ", ".join(map(str, (c for c in df.columns if c != pcol)))
            raise DataError(
                f"series {name!r}: column {column!r} not in sheet {sheet!r}; available: {avail}"
            )

        periods = _coerce_periods(df[pcol], name)
        values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
        out = pd.DataFrame({"period": periods, "series": name, "value": values})
        out = out[out["period"].notna()].reset_index(drop=True)  # drop unparseable period rows
        return self._clip_window(out)[LONG_COLUMNS]

    def _read_sheet(self, name: str, file: str, sheet: str) -> pd.DataFrame:
        path = Path(file)
        if not path.is_absolute() and self.data_root is not None:
            path = self.data_root / path
        key = (str(path), sheet)
        if key not in self._sheet_cache:
            if not path.exists():
                raise DataError(f"series {name!r}: workbook not found: {path}")
            try:
                self._sheet_cache[key] = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
            except ValueError as e:  # pandas raises ValueError for a missing sheet
                raise DataError(f"series {name!r}: sheet {sheet!r} not found in {path.name}") from e
        return self._sheet_cache[key]


def _coerce_periods(col: pd.Series, name: str) -> list:
    """Coerce a worksheet period column to pandas Periods.

    Handles, in order: our string tokens (2021Q1 / 2010M03 / 2024), datetimes
    (freq inferred from the median spacing), and bare year integers. Unparseable
    cells become NaT and are dropped by the caller. Returns a list aligned to
    `col`'s order, with a single inferred freq.
    """
    values = col.tolist()
    non_null = [v for v in values if pd.notna(v)]
    if not non_null:
        raise DataError(f"series {name!r}: period column is empty")

    # 1) string tokens
    if all(isinstance(v, str) for v in non_null):
        out = []
        for v in values:
            try:
                out.append(parse_period(v.strip()) if pd.notna(v) else pd.NaT)
            except DataError:
                out.append(pd.NaT)
        return _check_duplicate_periods(out, name)

    # 2) bare year integers (e.g. 2018, 2019, ...)
    if all(isinstance(v, (int,)) or (isinstance(v, float) and float(v).is_integer())
           for v in non_null) and all(1500 <= int(v) <= 2500 for v in non_null):
        out = [pd.Period(year=int(v), freq="Y") if pd.notna(v) else pd.NaT for v in values]
        return _check_duplicate_periods(out, name)

    # 3) datetimes — infer freq from median day spacing
    dt = pd.to_datetime(col, errors="coerce")
    if dt.notna().sum() == 0:
        raise DataError(f"series {name!r}: could not interpret period column ({col.name!r})")
    freq = _infer_period_freq(dt.dropna())
    out = [t.to_period(freq) if pd.notna(t) else pd.NaT for t in dt]
    return _check_duplicate_periods(out, name)


def _check_duplicate_periods(periods: list, name: str) -> list:
    """Raise DataError if the same period appears more than once (after NaT is excluded).

    Weekly data coerced to monthly freq is the common trigger — two dates in
    the same month both map to the same Period, producing duplicate rows that
    corrupt every downstream operation silently.
    """
    seen, dupes = set(), set()
    for p in periods:
        if pd.isna(p):
            continue
        key = str(p)
        if key in seen:
            dupes.add(key)
        seen.add(key)
    if dupes:
        examples = ", ".join(sorted(dupes)[:3])
        raise DataError(
            f"series {name!r}: duplicate periods after coercion ({examples}…); "
            f"data may be sub-monthly (weekly?) which is not supported — "
            f"aggregate to monthly/quarterly before loading"
        )
    return periods


def _infer_period_freq(dt: pd.Series) -> str:
    """Guess D/M/Q/Y from the median spacing of a datetime series.

    Daily allows for weekend/holiday gaps (business-day data medians ~1-3 days),
    so the threshold sits comfortably below weekly.
    """
    days = dt.sort_values().diff().dropna().dt.days
    if len(days) == 0:
        return "M"
    med = float(days.median())
    if med <= 3:
        return "D"
    if med <= 45:
        return "M"
    if med <= 200:
        return "Q"
    return "Y"
