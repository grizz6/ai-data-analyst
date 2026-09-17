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
