"""Charts for each dashboard tab, computed with Pandas and drawn as Plotly specs.

Every figure here is a picture of numbers computed elsewhere in the
pipeline or directly from the prepared data; nothing is estimated in the
browser. Point-heavy charts are drawn from a sample so the page stays fast.
"""

import math
from typing import Literal

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.models.schemas import ChartSpec, ClusterAnalysis, QualityIssue, StatisticalTests
from app.services.semantics import is_categorical
from app.services.timeaxis import TimeAxis
from app.utils.json_compat import plotly_figure_to_dict

SEED = 3
MAX_GRID = 12
GRID_COLUMNS = 3
MAX_CATEGORY_BARS = 12
SCATTER_MATRIX_COLUMNS = 4
SCATTER_POINTS = 1_000
MISSING_MAP_ROWS = 200
MAX_HEATMAP_COLUMNS = 25
HISTOGRAM_BINS = 30
BOX_OUTLIER_POINTS = 150


def build_visuals(
    raw_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    quality_issues: list[QualityIssue],
    statistics: StatisticalTests,
    clustering: ClusterAnalysis | None,
    axis: TimeAxis | None,
    identifiers: list[str],
) -> dict[str, list[ChartSpec]]:
    numeric = _numeric(metrics_df)
    categorical = _categorical(metrics_df)
    visuals = {
        "overview": [c for c in (_column_types(raw_df, metrics_df, identifiers), _completeness(raw_df)) if c],
        "quality": [
            c
            for c in (
                _missing_by_column(raw_df),
                _missing_map(raw_df),
                _outliers(metrics_df, numeric),
                _issues(quality_issues),
            )
            if c
        ],
        "explore": [
            c
            for c in (
                _histogram_grid(metrics_df, numeric),
                _category_grid(metrics_df, categorical),
                _box_grid(metrics_df, numeric),
                _rows_over_time(axis),
            )
            if c
        ],
        "relationships": [
            c
            for c in (
                _correlation_heatmap(metrics_df, numeric, "pearson"),
                _correlation_heatmap(metrics_df, numeric, "spearman"),
                _scatter_matrix(metrics_df, numeric, categorical),
                *_group_boxes(metrics_df, statistics),
                _cramers_heatmap(statistics, categorical),
                _crosstab(metrics_df, statistics),
            )
            if c
        ],
        "clustering": _clustering(clustering) if clustering else [],
    }
    return {tab: charts for tab, charts in visuals.items() if charts}


def _spec(fig: go.Figure, chart_id: str, title: str, chart_type: str, height: int | None = None) -> ChartSpec:
    fig.update_layout(title=title)
    if height:
        fig.update_layout(height=height)
    return ChartSpec(id=chart_id, title=title, chart_type=chart_type, plotly_json=plotly_figure_to_dict(fig))


def _numeric(df: pd.DataFrame) -> list[str]:
    return [
        str(c)
        for c in df.select_dtypes(include="number").columns
        if not pd.api.types.is_bool_dtype(df[c]) and df[c].nunique() > 1
    ]


def _categorical(df: pd.DataFrame) -> list[str]:
    return [
        str(c)
        for c in df.columns
        if not pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_datetime64_any_dtype(df[c])
        and is_categorical(df[c])
    ]


def _grid(count: int) -> tuple[int, int]:
    cols = min(GRID_COLUMNS, count)
    return math.ceil(count / cols), cols


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _column_types(raw: pd.DataFrame, metrics: pd.DataFrame, identifiers: list[str]) -> ChartSpec | None:
    counts = {
        "numbers": len(_numeric(metrics)),
        "categories": len(_categorical(metrics)),
        "dates": sum(pd.api.types.is_datetime64_any_dtype(metrics[c]) for c in metrics.columns),
        "identifiers": len(identifiers),
    }
    counts["other text"] = max(0, len(raw.columns) - sum(counts.values()))
    counts = {k: v for k, v in counts.items() if v}
    if not counts:
        return None
    fig = go.Figure(go.Pie(labels=list(counts), values=list(counts.values()), hole=0.55, textinfo="label+value"))
    fig.update_layout(showlegend=False)
    return _spec(fig, "column_types", "Column types", "pie", 320)


def _completeness(raw: pd.DataFrame) -> ChartSpec | None:
    if raw.empty:
        return None
    complete = int(raw.notna().all(axis=1).sum())
    duplicate = int(raw.duplicated().sum())
    values = {"complete rows": complete - duplicate, "rows with gaps": len(raw) - complete, "duplicate rows": duplicate}
    values = {k: max(0, v) for k, v in values.items() if v > 0}
    fig = go.Figure(go.Pie(labels=list(values), values=list(values.values()), hole=0.55, textinfo="label+percent"))
    fig.update_layout(showlegend=False)
    return _spec(fig, "row_completeness", "Rows", "pie", 320)


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------


def _missing_by_column(raw: pd.DataFrame) -> ChartSpec | None:
    share = (raw.isna().mean() * 100).round(2).sort_values()
    if raw.empty:
        return None
    fig = go.Figure(go.Bar(x=share.values, y=[str(c) for c in share.index], orientation="h"))
    fig.update_layout(xaxis_title="% missing", xaxis_range=[0, 100])
    return _spec(fig, "missing_by_column", "Missing values per column", "bar", max(300, 24 * len(share)))


def _missing_map(raw: pd.DataFrame) -> ChartSpec | None:
    gaps = raw.isna()
    if not gaps.to_numpy().any():
        return None
    sample = gaps.sample(n=min(len(gaps), MISSING_MAP_ROWS), random_state=SEED).sort_index()
    fig = px.imshow(
        sample.T.astype(int).to_numpy(),
        y=[str(c) for c in sample.columns],
        color_continuous_scale=[[0, "#1a2533"], [1, "#f87171"]],
        aspect="auto",
        labels={"x": "row (sample)", "color": "missing"},
    )
    fig.update_coloraxes(showscale=False)
    fig.update_xaxes(showticklabels=False)
    return _spec(fig, "missing_map", "Where values are missing", "heatmap", max(300, 22 * len(raw.columns)))


def _outliers(df: pd.DataFrame, numeric: list[str]) -> ChartSpec | None:
    counts = {}
    for col in numeric:
        values = df[col].dropna()
        if len(values) < 4:
            continue
        q1, q3 = values.quantile([0.25, 0.75])
        iqr = q3 - q1
        counts[col] = int(((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum())
    if not counts:
        return None
    ordered = sorted(counts.items(), key=lambda item: item[1])
    fig = go.Figure(go.Bar(x=[v for _, v in ordered], y=[k for k, _ in ordered], orientation="h"))
    fig.update_layout(xaxis_title="values outside 1.5 × IQR")
    return _spec(fig, "outliers_by_column", "Outliers per column", "bar", max(300, 24 * len(ordered)))


def _issues(issues: list[QualityIssue]) -> ChartSpec | None:
    if not issues:
        return None
    frame = pd.DataFrame([{"category": i.category, "severity": i.severity} for i in issues])
    counts = frame.groupby(["category", "severity"]).size().reset_index(name="issues")
    fig = px.bar(counts, x="issues", y="category", color="severity", orientation="h")
    return _spec(fig, "issues_by_kind", "Quality issues by kind", "bar", 320)


# ---------------------------------------------------------------------------
# Explore
# ---------------------------------------------------------------------------


def _histogram_grid(df: pd.DataFrame, numeric: list[str]) -> ChartSpec | None:
    """Binned here, so the chart carries 30 bars per column rather than every value."""
    cols = numeric[:MAX_GRID]
    if not cols:
        return None
    rows, ncols = _grid(len(cols))
    fig = make_subplots(rows=rows, cols=ncols, subplot_titles=cols)
    for i, col in enumerate(cols):
        values = df[col].dropna().to_numpy(dtype=float)
        counts, edges = np.histogram(values, bins=HISTOGRAM_BINS)
        fig.add_trace(
            go.Bar(
                x=((edges[:-1] + edges[1:]) / 2).round(6),
                y=counts,
                width=float(edges[1] - edges[0]),
                showlegend=False,
                hovertemplate="%{x}<br>%{y} rows<extra></extra>",
            ),
            row=i // ncols + 1,
            col=i % ncols + 1,
        )
    fig.update_layout(bargap=0.02)
    return _spec(fig, "histograms", "Distribution of every numeric column", "histogram", 240 * rows + 60)


def _category_grid(df: pd.DataFrame, categorical: list[str]) -> ChartSpec | None:
    cols = categorical[:MAX_GRID]
    if not cols:
        return None
    rows, ncols = _grid(len(cols))
    fig = make_subplots(rows=rows, cols=ncols, subplot_titles=cols)
    for i, col in enumerate(cols):
        counts = df[col].value_counts().head(MAX_CATEGORY_BARS)
        fig.add_trace(
            go.Bar(x=counts.index.astype(str), y=counts.values, showlegend=False), row=i // ncols + 1, col=i % ncols + 1
        )
    return _spec(fig, "category_counts", "Count of each category", "bar", 260 * rows + 60)


def _box_grid(df: pd.DataFrame, numeric: list[str]) -> ChartSpec | None:
    """Box statistics are computed here; only a sample of the outliers is drawn as points."""
    cols = numeric[:MAX_GRID]
    if not cols:
        return None
    rows, ncols = _grid(len(cols))
    fig = make_subplots(rows=rows, cols=ncols, subplot_titles=cols)
    for i, col in enumerate(cols):
        values = df[col].dropna().astype(float)
        q1, median, q3 = (float(v) for v in values.quantile([0.25, 0.5, 0.75]))
        reach = 1.5 * (q3 - q1)
        inside = values[values.between(q1 - reach, q3 + reach)]
        outliers = values[~values.index.isin(inside.index)]
        if len(outliers) > BOX_OUTLIER_POINTS:
            outliers = outliers.sample(n=BOX_OUTLIER_POINTS, random_state=SEED)
        position = dict(row=i // ncols + 1, col=i % ncols + 1)
        fig.add_trace(
            go.Box(
                x=[col],
                q1=[q1],
                median=[median],
                q3=[q3],
                lowerfence=[float(inside.min())],
                upperfence=[float(inside.max())],
                mean=[float(values.mean())],
                boxpoints=False,
                showlegend=False,
                name=col,
            ),
            **position,
        )
        if len(outliers):
            fig.add_trace(
                go.Scatter(
                    x=[col] * len(outliers),
                    y=outliers.to_numpy(),
                    mode="markers",
                    marker={"size": 4, "opacity": 0.5},
                    showlegend=False,
                    name="outliers",
                ),
                **position,
            )
    return _spec(fig, "box_plots", "Spread and outliers of every numeric column", "box", 240 * rows + 60)


def _rows_over_time(axis: TimeAxis | None) -> ChartSpec | None:
    if axis is None or not axis.is_calendar:
        return None
    stamps = axis.values.dropna()
    if stamps.nunique() < 2:
        return None
    span_days = (stamps.max() - stamps.min()).days
    freq, label = ("D", "day") if span_days <= 120 else ("W", "week") if span_days <= 1_000 else ("M", "month")
    counts = stamps.dt.to_period(freq).dt.start_time.value_counts().sort_index()
    fig = go.Figure(go.Bar(x=counts.index, y=counts.values))
    fig.update_layout(xaxis_title=axis.label, yaxis_title=f"rows per {label}")
    return _spec(fig, "rows_over_time", f"Rows per {label}", "bar", 320)


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


def _correlation_heatmap(
    df: pd.DataFrame, numeric: list[str], method: Literal["pearson", "spearman"]
) -> ChartSpec | None:
    cols = numeric[:MAX_HEATMAP_COLUMNS]
    if len(cols) < 2:
        return None
    corr = df[cols].corr(method=method).round(2)
    fig = px.imshow(corr, text_auto=len(cols) <= 12, color_continuous_scale="RdBu", zmin=-1, zmax=1, aspect="auto")
    name = "Pearson (straight-line)" if method == "pearson" else "Spearman (rank, any monotonic shape)"
    return _spec(fig, f"corr_{method}", f"Correlation: {name}", "heatmap", max(360, 28 * len(cols) + 120))


def _scatter_matrix(df: pd.DataFrame, numeric: list[str], categorical: list[str]) -> ChartSpec | None:
    if len(numeric) < 2:
        return None
    cols = sorted(numeric, key=lambda c: -float(df[c].std() / (abs(df[c].mean()) + 1e-9)))[:SCATTER_MATRIX_COLUMNS]
    sample = df.sample(n=min(len(df), SCATTER_POINTS), random_state=SEED)
    colour = next((c for c in categorical if 2 <= df[c].nunique() <= 8), None)
    fig = px.scatter_matrix(sample, dimensions=cols, color=colour, opacity=0.55)
    fig.update_traces(diagonal_visible=False, marker={"size": 4}, showupperhalf=False)
    title = "Scatter matrix" + (f" (colour: {colour})" if colour else "")
    return _spec(fig, "scatter_matrix", title, "scatter", 520)


def _group_boxes(df: pd.DataFrame, statistics: StatisticalTests) -> list[ChartSpec]:
    charts = []
    for diff in statistics.group_differences[:3]:
        order = (
            df.groupby(diff.group_column, observed=True)[diff.value_column].median().sort_values(ascending=False).index
        )
        frame = df[[diff.group_column, diff.value_column]].dropna()
        frame = frame.sample(n=min(len(frame), 5_000), random_state=SEED)
        fig = px.box(
            frame,
            x=diff.group_column,
            y=diff.value_column,
            category_orders={diff.group_column: [str(o) for o in order]},
        )
        title = f"{diff.value_column} by {diff.group_column} (η² {diff.eta_squared:.2f})"
        charts.append(_spec(fig, f"group_{diff.group_column}_{diff.value_column}", title, "box", 360))
    return charts


def _cramers_heatmap(statistics: StatisticalTests, categorical: list[str]) -> ChartSpec | None:
    pairs = statistics.categorical_associations
    names = sorted(
        {p.column_a for p in pairs} | {p.column_b for p in pairs}, key=categorical.index if categorical else None
    )
    if len(names) < 2:
        return None
    matrix = pd.DataFrame(np.eye(len(names)), index=names, columns=names)
    for p in pairs:
        matrix.loc[p.column_a, p.column_b] = matrix.loc[p.column_b, p.column_a] = p.cramers_v
    fig = px.imshow(matrix.round(2), text_auto=True, color_continuous_scale="Blues", zmin=0, zmax=1, aspect="auto")
    return _spec(
        fig, "cramers_v", "Association between categories (Cramér's V)", "heatmap", max(320, 40 * len(names) + 120)
    )


def _crosstab(df: pd.DataFrame, statistics: StatisticalTests) -> ChartSpec | None:
    if not statistics.categorical_associations:
        return None
    top = statistics.categorical_associations[0]
    table = pd.crosstab(df[top.column_a], df[top.column_b], normalize="index").round(4) * 100
    table = table.loc[table.index[:MAX_CATEGORY_BARS]]
    fig = go.Figure(
        [
            go.Bar(name=str(col), x=[str(i) for i in table.index], y=table[col].values)
            for col in table.columns[:MAX_CATEGORY_BARS]
        ]
    )
    fig.update_layout(
        barmode="stack", xaxis_title=top.column_a, yaxis_title=f"% by {top.column_b}", legend={"orientation": "h"}
    )
    return _spec(fig, "crosstab", f"{top.column_b} within each {top.column_a}", "bar", 380)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _clustering(c: ClusterAnalysis) -> list[ChartSpec]:
    charts = []
    ks = list(range(2, 2 + len(c.k_scores)))
    fig = go.Figure(go.Scatter(x=ks, y=c.k_scores, mode="lines+markers"))
    fig.add_hline(y=0.25, line_dash="dot")
    fig.add_vline(x=c.k, line_dash="dot")
    fig.update_layout(xaxis_title="number of groups (k)", yaxis_title="silhouette score")
    charts.append(_spec(fig, "silhouette_by_k", "Choosing the number of groups", "line", 320))

    ordered = sorted(c.clusters, key=lambda p: p.cluster)
    fig = go.Figure(go.Bar(x=[f"Group {p.cluster}" for p in ordered], y=[p.size for p in ordered]))
    fig.update_layout(yaxis_title="rows")
    charts.append(_spec(fig, "cluster_sizes", "Rows in each group", "bar", 320))

    if c.centers:
        fig = px.imshow(
            np.array(c.centers),
            x=c.features,
            y=[f"Group {i + 1}" for i in range(len(c.centers))],
            color_continuous_scale="RdBu",
            zmin=-2,
            zmax=2,
            text_auto=".1f",
            aspect="auto",
            labels={"color": "SD from avg"},
        )
        charts.append(_spec(fig, "cluster_profiles", "Group profiles (SD from the average)", "heatmap", 320))

    if c.pca_explained:
        components = [f"PC{i + 1}" for i in range(len(c.pca_explained))]
        fig = go.Figure(go.Bar(x=components, y=[v * 100 for v in c.pca_explained], name="each"))
        fig.add_trace(
            go.Scatter(x=components, y=np.cumsum(c.pca_explained) * 100, mode="lines+markers", name="cumulative")
        )
        fig.update_layout(yaxis_title="% of variation", legend={"orientation": "h"})
        charts.append(_spec(fig, "pca_variance", "Variation captured by each component", "bar", 320))
    if c.chart:
        charts.append(c.chart)
    return charts
