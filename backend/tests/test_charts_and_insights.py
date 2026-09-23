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


def chart(df, chart_type):
    return next(c for c in build_charts(df) if c.chart_type == chart_type)


def test_scatter_plots_the_most_correlated_pair_not_the_first_two_columns():
    x, y = correlated_pair(80, 0.95, seed=4)
    noise, _ = correlated_pair(80, 0.0, seed=5)
    df = pd.DataFrame({"x": x, "noise": noise, "y": y})
    assert chart(df, "scatter").title == "x vs y"


def test_box_plot_gives_each_column_its_own_axis():
    df = pd.DataFrame({"sales": [9000.0, 12000, 15000, 11000], "units": [90.0, 120, 150, 110]})
    fig = chart(df, "box").plotly_json
    assert [t["name"] for t in fig["data"]] == ["sales", "units"]
    assert {t["yaxis"] for t in fig["data"]} == {"y", "y2"}


def test_mostly_unique_text_gets_no_bar_chart():
    n = 80
    df = pd.DataFrame(
        {
            "customer_name": [f"Customer {i}" for i in range(n)],
            "region": ["West", "East", "North", "South"] * (n // 4),
            "spend": range(n),
        }
    )
    bars = [c.title for c in build_charts(df) if c.chart_type == "bar"]
    assert bars == ["Top categories in region"]


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
