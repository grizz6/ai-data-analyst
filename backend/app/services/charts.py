import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.models.schemas import ChartSpec
from app.utils.json_compat import plotly_figure_to_dict

CHART_ROW_LIMIT = 50_000


def _sample_for_charts(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= CHART_ROW_LIMIT:
        return df
    return df.sample(n=CHART_ROW_LIMIT, random_state=42)


def build_charts(df: pd.DataFrame, max_charts: int = 8) -> list[ChartSpec]:
    df = _sample_for_charts(df)
    charts: list[ChartSpec] = []
    numeric_cols = list(df.select_dtypes(include="number").columns)
    cat_cols = [
        c
        for c in df.columns
        if c not in numeric_cols and not pd.api.types.is_datetime64_any_dtype(df[c])
    ]
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]

    for col in numeric_cols[:3]:
        fig = px.histogram(df, x=col, nbins=30, title=f"Distribution of {col}")
        charts.append(
            ChartSpec(
                id=f"hist_{col}",
                title=f"Distribution of {col}",
                chart_type="histogram",
                plotly_json=plotly_figure_to_dict(fig),
            )
        )

    for col in cat_cols[:2]:
        counts = df[col].value_counts().head(12)
        fig = px.bar(
            x=counts.index.astype(str),
            y=counts.values,
            labels={"x": col, "y": "Count"},
            title=f"Top categories in {col}",
        )
        charts.append(
            ChartSpec(
                id=f"bar_{col}",
                title=f"Top categories in {col}",
                chart_type="bar",
                plotly_json=plotly_figure_to_dict(fig),
            )
        )

    if len(numeric_cols) >= 2:
        fig = px.scatter(
            df,
            x=numeric_cols[0],
            y=numeric_cols[1],
            title=f"{numeric_cols[0]} vs {numeric_cols[1]}",
            opacity=0.6,
        )
        charts.append(
            ChartSpec(
                id="scatter_pair",
                title=f"{numeric_cols[0]} vs {numeric_cols[1]}",
                chart_type="scatter",
                plotly_json=plotly_figure_to_dict(fig),
            )
        )

    if len(numeric_cols) >= 2:
        corr = df[numeric_cols].corr()
        fig = go.Figure(
            data=go.Heatmap(
                z=corr.values,
                x=list(corr.columns),
                y=list(corr.index),
                colorscale="RdBu",
                zmid=0,
            )
        )
        fig.update_layout(title="Correlation heatmap (numeric columns)")
        charts.append(
            ChartSpec(
                id="corr_heatmap",
                title="Correlation heatmap",
                chart_type="heatmap",
                plotly_json=plotly_figure_to_dict(fig),
            )
        )

    if date_cols and numeric_cols:
        date_col = date_cols[0]
        num_col = numeric_cols[0]
        grouped = (
            df.dropna(subset=[date_col, num_col])
            .sort_values(date_col)
            .groupby(pd.Grouper(key=date_col, freq="D"))[num_col]
            .mean()
            .reset_index()
        )
        if len(grouped) > 1:
            fig = px.line(
                grouped,
                x=date_col,
                y=num_col,
                title=f"{num_col} over time",
            )
            charts.append(
                ChartSpec(
                    id="timeseries",
                    title=f"{num_col} over time",
                    chart_type="line",
                    plotly_json=plotly_figure_to_dict(fig),
                )
            )

    if numeric_cols:
        melted = df[numeric_cols].melt(var_name="column", value_name="value").dropna()
        if not melted.empty:
            fig = px.box(melted, x="column", y="value", title="Numeric distributions (box plot)")
            charts.append(
                ChartSpec(
                    id="box_numeric",
                    title="Numeric distributions",
                    chart_type="box",
                    plotly_json=plotly_figure_to_dict(fig),
                )
            )

    return charts[:max_charts]
