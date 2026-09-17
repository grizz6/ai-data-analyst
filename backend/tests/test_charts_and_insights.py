import pandas as pd

from app.models.schemas import CorrelationPair
from app.services.charts import build_charts
from app.services.insights import generate_rule_insights
from tests.builders import correlated_pair


def test_charts_cover_each_column_kind_and_respect_the_cap():
    x, y = correlated_pair(60, 0.9)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=60),
            "region": ["West", "East", "North"] * 20,
            "sales": x,
            "units": y,
        }
    )
    charts = build_charts(df)
    kinds = {c.chart_type for c in charts}

    assert {"histogram", "bar", "scatter", "heatmap", "line", "box"} <= kinds
    assert len(charts) <= 8
    assert all("data" in c.plotly_json for c in charts)


def timeseries_chart(df):
    return next(c for c in build_charts(df) if c.chart_type == "line")


def test_weekly_data_draws_one_connected_point_per_week():
    df = pd.DataFrame(
        {"date": pd.date_range("2024-01-05", periods=31, freq="W"), "sales": range(31)}
    )
    chart = timeseries_chart(df)
    trace = chart.plotly_json["data"][0]

    assert len(trace["y"]) == 31
    assert None not in trace["y"]
    assert "markers" in trace["mode"]


def test_long_daily_history_is_bucketed_to_stay_readable():
    days = 3 * 365
    df = pd.DataFrame(
        {"date": pd.date_range("2020-01-01", periods=days, freq="D"), "sales": range(days)}
    )
    chart = timeseries_chart(df)
    trace = chart.plotly_json["data"][0]

    assert "weekly" in chart.title
    assert len(trace["y"]) <= 366
    assert None not in trace["y"]


def test_correlation_strength_wording():
    df = pd.DataFrame({"a": [1, 2, 3]})
    pairs = [
        CorrelationPair(column_a="a", column_b="b", correlation=0.82),
        CorrelationPair(column_a="c", column_b="d", correlation=-0.55),
    ]
    insights = generate_rule_insights(df, [], [], [], pairs, [])
    messages = [i.message for i in insights if i.category == "correlation"]

    assert messages[0].startswith("Strong positive correlation")
    assert messages[1].startswith("Moderate negative correlation")
