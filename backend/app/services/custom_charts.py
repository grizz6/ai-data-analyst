"""Charts the user asks for by picking a chart type and columns.

Like the automatic charts, these are drawn from the prepared data: duplicates
removed and types fixed, but no filled-in values, so a chart never shows a
number that wasn't in the file. Identifier columns can't be charted.
"""

import io

import pandas as pd
import plotly.express as px

from app.models.schemas import AnalysisResult, ChartSpec, CustomChartRequest
from app.services.charts import MARKER_POINT_LIMIT, _sample_for_charts, _time_bucket
from app.utils.json_compat import plotly_figure_to_dict

MAX_BARS = 20
MAX_BOX_GROUPS = 12

AGGREGATE_LABELS = {"count": "Count", "sum": "Total", "mean": "Average", "median": "Median"}


class ChartRequestError(ValueError):
    """The requested chart doesn't fit the chosen columns. The message is for the user."""


def load_chart_data(result: AnalysisResult, chart_csv: bytes) -> pd.DataFrame:
    """Read the stored prepared data back with the types it had when analyzed."""
    text_cols = {c.name for c in result.columns if c.dtype in ("object", "string", "category", "bool")}
    df = pd.read_csv(io.BytesIO(chart_csv), dtype={c: str for c in text_cols}, encoding="utf-8-sig")
    for col in result.columns:
        if col.dtype.startswith("datetime") and col.name in df.columns:
            df[col.name] = pd.to_datetime(df[col.name], errors="coerce")
    return df


def build_custom_chart(df: pd.DataFrame, req: CustomChartRequest) -> ChartSpec:
    df = _sample_for_charts(df)
    for name in (req.x, req.y):
        if name is not None and name not in df.columns:
            raise ChartRequestError(f"'{name}' can't be charted: it isn't in the data or is an identifier column.")

    builders = {
        "histogram": _histogram,
        "bar": _bar,
        "scatter": _scatter,
        "line": _line,
        "box": _box,
    }
    fig, title = builders[req.chart_type](df, req)
    return ChartSpec(
        id=f"custom_{req.chart_type}_{req.x}_{req.y or ''}_{req.aggregate}",
        title=title,
        chart_type=req.chart_type,
        plotly_json=plotly_figure_to_dict(fig),
    )


def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _is_date(series: pd.Series) -> bool:
    return pd.api.types.is_datetime64_any_dtype(series)


def _require_numeric(df: pd.DataFrame, col: str | None, role: str) -> str:
    if col is None:
        raise ChartRequestError(f"Choose a numeric column for {role}.")
    if not _is_numeric(df[col]):
        raise ChartRequestError(f"'{col}' isn't numeric, so it can't be used for {role}.")
    if not df[col].notna().any():
        raise ChartRequestError(f"'{col}' has no values to chart.")
    return col


def _aggregate(grouped, req: CustomChartRequest):
    if req.aggregate == "count" or req.y is None:
        return grouped.size()
    return grouped[req.y].agg(req.aggregate)


def _value_label(req: CustomChartRequest) -> str:
    if req.aggregate == "count" or req.y is None:
        return "Count"
    return f"{AGGREGATE_LABELS[req.aggregate]} {req.y}"


def _histogram(df: pd.DataFrame, req: CustomChartRequest):
    x = _require_numeric(df, req.x, "a histogram")
    return px.histogram(df, x=x, nbins=30), f"Distribution of {x}"


def _require_x(req: CustomChartRequest) -> str:
    if req.x is None:
        raise ChartRequestError(f"Choose a column for the x axis of the {req.chart_type} chart.")
    return req.x


def _bar(df: pd.DataFrame, req: CustomChartRequest):
    _require_x(req)
    if _is_date(df[req.x]):
        raise ChartRequestError(f"'{req.x}' holds dates; use a line chart to show values over time.")
    if req.aggregate != "count":
        _require_numeric(df, req.y, f"the {req.aggregate}")
    rows = df.dropna(subset=[req.x] + ([req.y] if req.y and req.aggregate != "count" else []))
    values = _aggregate(rows.groupby(req.x, observed=True), req).dropna()
    if values.empty:
        raise ChartRequestError("There are no rows with values in both columns.")
    shown = values.sort_values(ascending=False).head(MAX_BARS)
    label = _value_label(req)
    fig = px.bar(x=shown.index.astype(str), y=shown.values, labels={"x": req.x, "y": label})
    more = f" (top {MAX_BARS} of {len(values)})" if len(values) > MAX_BARS else ""
    return fig, f"{label} by {req.x}{more}"


def _scatter(df: pd.DataFrame, req: CustomChartRequest):
    x = _require_numeric(df, req.x, "the x axis")
    y = _require_numeric(df, req.y, "the y axis")
    if x == y:
        raise ChartRequestError("Choose two different columns for a scatter plot.")
    return px.scatter(df, x=x, y=y, opacity=0.6), f"{x} vs {y}"


def _line(df: pd.DataFrame, req: CustomChartRequest):
    _require_x(req)
    if not (_is_date(df[req.x]) or _is_numeric(df[req.x])):
        raise ChartRequestError(f"'{req.x}' needs to hold dates or numbers for a line chart.")
    if req.aggregate != "count":
        _require_numeric(df, req.y, "the line")
    keep = [req.x] + ([req.y] if req.y and req.aggregate != "count" else [])
    rows = df.dropna(subset=keep)
    if rows.empty:
        raise ChartRequestError("There are no rows with values in both columns.")

    label = _value_label(req)
    if _is_date(rows[req.x]):
        freq, bucket = _time_bucket(rows[req.x])
        series = _aggregate(rows.groupby(pd.Grouper(key=req.x, freq=freq)), req)
        title = f"{label} over {req.x} ({bucket})"
    else:
        series = _aggregate(rows.groupby(req.x), req)
        title = f"{label} by {req.x}"
    series = series.dropna()
    if len(series) < 2:
        raise ChartRequestError("A line needs at least two points; this choice gives fewer.")
    fig = px.line(
        x=series.index, y=series.values, labels={"x": req.x, "y": label}, markers=len(series) <= MARKER_POINT_LIMIT
    )
    return fig, title


def _box(df: pd.DataFrame, req: CustomChartRequest):
    """y is the measured value; x, if given, splits it into one box per category."""
    value = _require_numeric(df, req.y, "a box plot")
    if req.x is None:
        return px.box(df, y=value), f"Spread of {value}"
    group = req.x
    if _is_numeric(df[group]) or _is_date(df[group]):
        raise ChartRequestError(f"Split a box plot by a text column; '{group}' isn't one.")
    top = df[group].value_counts().head(MAX_BOX_GROUPS).index
    rows = df[df[group].isin(top)].dropna(subset=[value])
    fig = px.box(rows, x=group, y=value, category_orders={group: [str(t) for t in top]})
    return fig, f"Spread of {value} by {group}"
