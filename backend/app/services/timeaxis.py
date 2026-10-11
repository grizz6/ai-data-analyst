"""Find what orders a file's rows in time, even when there is no date column.

Checked in this order, first match wins:

1. A column already parsed as dates.
2. Date parts in separate columns: year with month (and day, hour), year
   with quarter, or year with week. Month names ("Jan", "March") count.
3. Unix timestamps: whole numbers in the seconds, milliseconds or
   microseconds range for 2000-2050, in a column whose name suggests time
   or whose values only increase (so IDs in that range aren't mistaken).
4. A year column on its own (1800-2100).
5. A step column: a numeric column named like t, step, period or index
   whose values only increase.
6. Row order, only when values depend on the rows before them (Ljung-Box
   test) and the file isn't simply sorted by a value or grouped by a
   category, either of which fakes that dependence.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.services.semantics import name_words

MIN_ROWS = 8
MIN_SEQUENCE_ROWS = 30
LJUNG_BOX_ALPHA = 0.01
# Runs of the same category shorter than this share of the expected count mean grouped rows.
GROUPED_RUN_RATIO = 0.2
MONOTONIC_SHARE = 0.95

YEAR_WORDS = {"year", "yr", "yyyy"}
MONTH_WORDS = {"month", "mon", "mm"}
DAY_WORDS = {"day", "dd", "dom"}
HOUR_WORDS = {"hour", "hr", "hh"}
QUARTER_WORDS = {"quarter", "qtr", "q"}
WEEK_WORDS = {"week", "wk", "weeknum"}
TIME_WORDS = {"time", "timestamp", "ts", "epoch", "created", "updated", "date", "datetime", "at", "when"}
STEP_WORDS = {
    "t",
    "step",
    "steps",
    "period",
    "tick",
    "index",
    "idx",
    "seq",
    "sequence",
    "cycle",
    "frame",
    "iteration",
    "round",
    "trial",
}

MONTH_NAMES = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}

# Unix time for 2000-01-01 and 2050-01-01, in seconds.
EPOCH_LOW, EPOCH_HIGH = 946_684_800, 2_524_608_000
EPOCH_UNITS = [("s", 1), ("ms", 1_000), ("us", 1_000_000)]


@dataclass
class TimeAxis:
    # "dates", "date_parts", "epoch", "year", "step_column" or "row_order"
    kind: str
    columns: list[str]
    label: str
    # Datetimes for the calendar kinds; increasing numbers for steps and row order.
    values: pd.Series

    @property
    def is_calendar(self) -> bool:
        return pd.api.types.is_datetime64_any_dtype(self.values)


def find_time_axis(df: pd.DataFrame) -> TimeAxis | None:
    if len(df) < MIN_ROWS:
        return None
    for finder in (_date_column, _date_parts, _epoch, _year_only, _step_column, _row_order):
        axis = finder(df)
        if axis is not None and axis.values.notna().sum() >= MIN_ROWS:
            return axis
    return None


def _words(col) -> set[str]:
    return {w.lower() for w in name_words(str(col))}


def _named(df: pd.DataFrame, words: set[str]) -> str | None:
    for col in df.columns:
        lowered = str(col).strip().lower()
        if lowered in words or _words(col) & words and len(_words(col)) <= 2:
            return str(col)
    return None


def _date_column(df: pd.DataFrame) -> TimeAxis | None:
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return TimeAxis("dates", [str(col)], str(col), df[col])
    return None


def _as_int(series: pd.Series, low: int, high: int) -> pd.Series | None:
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().mean() < 0.9:
        return None
    present = values.dropna()
    if not ((present % 1 == 0).all() and present.between(low, high).all()):
        return None
    return values


def _month_values(series: pd.Series) -> pd.Series | None:
    numbers = _as_int(series, 1, 12)
    if numbers is not None:
        return numbers
    names = series.astype(str).str.strip().str.lower().map(MONTH_NAMES)
    return names if names.notna().mean() >= 0.9 else None


def _date_parts(df: pd.DataFrame) -> TimeAxis | None:
    year_col = _named(df, YEAR_WORDS)
    if year_col is None:
        return None
    years = _as_int(df[year_col], 1800, 2100)
    if years is None:
        return None

    month_col = _named(df, MONTH_WORDS)
    months = _month_values(df[month_col]) if month_col else None
    if month_col and months is not None:
        parts = {"year": years, "month": months, "day": 1}
        cols = [year_col, month_col]
        for words, key, low, high in ((DAY_WORDS, "day", 1, 31), (HOUR_WORDS, "hour", 0, 23)):
            col = _named(df, words)
            values = _as_int(df[col], low, high) if col else None
            if col and values is not None:
                parts[key] = values
                cols.append(col)
        stamps = pd.to_datetime(pd.DataFrame(parts, index=df.index), errors="coerce")
        return TimeAxis("date_parts", cols, " + ".join(cols), stamps)

    quarter_col = _named(df, QUARTER_WORDS)
    quarters = _as_int(df[quarter_col].astype(str).str.upper().str.lstrip("Q"), 1, 4) if quarter_col else None
    if quarter_col and quarters is not None:
        stamps = pd.to_datetime(
            pd.DataFrame({"year": years, "month": (quarters - 1) * 3 + 1, "day": 1}, index=df.index), errors="coerce"
        )
        return TimeAxis("date_parts", [year_col, quarter_col], f"{year_col} + {quarter_col}", stamps)

    week_col = _named(df, WEEK_WORDS)
    weeks = _as_int(df[week_col], 1, 53) if week_col else None
    if week_col and weeks is not None:
        text = years.astype("Int64").astype(str) + "-W" + weeks.astype("Int64").astype(str).str.zfill(2) + "-1"
        stamps = pd.to_datetime(text, format="%G-W%V-%u", errors="coerce")
        return TimeAxis("date_parts", [year_col, week_col], f"{year_col} + {week_col}", stamps)
    return None


def _increasing(values: pd.Series) -> bool:
    steps = values.dropna().astype(float).diff().dropna().to_numpy()
    return len(steps) > 0 and bool((steps >= 0).mean() >= MONOTONIC_SHARE)


def _epoch(df: pd.DataFrame) -> TimeAxis | None:
    for col in df.select_dtypes(include="number").columns:
        values = df[col]
        present = values.dropna()
        if present.empty or not (present % 1 == 0).all():
            continue
        for unit, scale in EPOCH_UNITS:
            if present.between(EPOCH_LOW * scale, EPOCH_HIGH * scale).all():
                if _words(col) & TIME_WORDS or _increasing(values):
                    stamps = pd.to_datetime(values, unit=unit, errors="coerce")
                    names = {"s": "seconds", "ms": "milliseconds", "us": "microseconds"}
                    return TimeAxis("epoch", [str(col)], f"{col} (Unix {names[unit]})", stamps)
                break
    return None


def _year_only(df: pd.DataFrame) -> TimeAxis | None:
    year_col = _named(df, YEAR_WORDS)
    if year_col is None:
        return None
    years = _as_int(df[year_col], 1800, 2100)
    if years is None or years.nunique() < MIN_ROWS:
        return None
    stamps = pd.to_datetime(years.astype("Int64").astype(str), format="%Y", errors="coerce")
    return TimeAxis("year", [year_col], year_col, stamps)


def _step_column(df: pd.DataFrame) -> TimeAxis | None:
    for col in df.select_dtypes(include="number").columns:
        if (
            _words(col) & STEP_WORDS
            and len(_words(col)) <= 2
            and _increasing(df[col])
            and df[col].nunique() >= MIN_ROWS
        ):
            return TimeAxis("step_column", [str(col)], str(col), df[col].astype(float))
    return None


def _row_order(df: pd.DataFrame) -> TimeAxis | None:
    from statsmodels.stats.diagnostic import acorr_ljungbox

    if len(df) < MIN_SEQUENCE_ROWS:
        return None
    numeric = [c for c in df.select_dtypes(include="number").columns if df[c].nunique() > 2]
    if not numeric or _sorted_or_grouped(df, numeric):
        return None
    lags = max(1, min(10, len(df) // 5))
    for col in numeric[:10]:
        values = df[col].dropna().to_numpy(dtype=float)
        if len(values) < MIN_SEQUENCE_ROWS or np.ptp(values) == 0:
            continue
        p = float(acorr_ljungbox(values, lags=[lags])["lb_pvalue"].iloc[0])
        if p < LJUNG_BOX_ALPHA:
            steps = pd.Series(np.arange(len(df), dtype=float), index=df.index)
            return TimeAxis("row_order", [], "row order", steps)
    return None


def _sorted_or_grouped(df: pd.DataFrame, numeric: list) -> bool:
    """Sorting by a value or grouping by a category makes neighbouring rows alike without any time order."""
    if any(_increasing(df[c]) or _increasing(-df[c]) for c in numeric):
        return True
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_numeric_dtype(series) or not 2 <= series.nunique() <= 50:
            continue
        values = series.dropna().astype(str)
        runs = int((values != values.shift()).sum())
        shares = values.value_counts(normalize=True)
        expected_runs = 1 + (len(values) - 1) * (1 - float((shares**2).sum()))
        if runs < GROUPED_RUN_RATIO * expected_runs:
            return True
    return False
