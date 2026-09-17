import pandas as pd
import pytest

from app.services.analysis import (
    categorical_summaries,
    detect_trends,
    numeric_summaries,
    top_correlations,
)
from tests.builders import correlated_pair, weekly_series


def test_numeric_summary_matches_pandas():
    df = pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0, 100.0]})
    [summary] = numeric_summaries(df)
    assert summary.count == 5
    assert summary.mean == pytest.approx(22.0)
    assert summary.median == pytest.approx(3.0)
    assert summary.min == 1.0 and summary.max == 100.0


def test_categorical_summary_orders_by_frequency():
    df = pd.DataFrame({"region": ["West", "East", "West", "North", "West", "East"]})
    [summary] = categorical_summaries(df)
    assert [v["value"] for v in summary.top_values] == ["West", "East", "North"]


def test_planted_correlation_is_found_and_weak_pair_is_not():
    x, y = correlated_pair(200, 0.87, seed=1)
    a, b = correlated_pair(200, 0.30, seed=2)
    df = pd.DataFrame({"x": x, "y": y, "a": a, "b": b})
    pairs = {(p.column_a, p.column_b): p.correlation for p in top_correlations(df)}

    assert pairs[("x", "y")] == pytest.approx(0.87, abs=1e-4)
    assert ("a", "b") not in pairs


def test_date_trend_rising_thirty_percent_is_up():
    [trend] = detect_trends(weekly_series(100, 130))
    assert trend.direction == "up"
    assert trend.change_pct == pytest.approx(30.0)


def test_date_trend_moving_two_percent_is_stable():
    [trend] = detect_trends(weekly_series(100, 102))
    assert trend.direction == "stable"
