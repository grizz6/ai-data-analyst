import numpy as np
import pandas as pd
import pytest

from app.services.analysis import (
    categorical_summaries,
    detect_trends,
    numeric_summaries,
    top_correlations,
)
from app.services.insights import generate_rule_insights
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


def test_correlation_carries_sample_size_and_p_value():
    x, y = correlated_pair(200, 0.87, seed=1)
    [pair] = top_correlations(pd.DataFrame({"x": x, "y": y}))
    assert pair.n == 200
    assert pair.p_value < 1e-10


def test_correlation_only_counts_rows_where_both_columns_have_values():
    x, y = correlated_pair(50, 0.9, seed=3)
    df = pd.DataFrame({"x": x, "y": y})
    df.loc[:9, "y"] = None
    [pair] = top_correlations(df)
    assert pair.n == 40


def test_small_sample_correlation_is_called_out_as_possible_chance():
    df = pd.DataFrame({"a": [1.0, 2, 3, 4, 5], "b": [2.0, 1, 4, 3, 5]})
    [pair] = top_correlations(df)
    assert pair.correlation >= 0.5 and pair.p_value >= 0.05  # precondition: big r, tiny n

    [message] = [i.message for i in generate_rule_insights(df, [], [], [], [pair], []) if i.category == "correlation"]
    assert "n = 5" in message
    assert "could be chance" in message


def test_daily_trend_reports_slope_per_day():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    [trend] = detect_trends(pd.DataFrame({"date": dates, "sales": [100.0 + 2 * i for i in range(30)]}))
    assert trend.direction == "up"
    assert (trend.slope, trend.slope_unit) == (pytest.approx(2.0), "day")
    assert trend.p_value < 0.001
    assert "p < 0.001" in trend.message


def test_long_trend_reports_slope_per_month():
    dates = pd.date_range("2023-01-01", periods=365, freq="D")
    [trend] = detect_trends(pd.DataFrame({"date": dates, "sales": [100.0 + i for i in range(365)]}))
    assert (trend.slope, trend.slope_unit) == (pytest.approx(30.44, rel=1e-3), "month")


def test_big_but_noisy_change_is_not_called_a_trend():
    first = [100.0, 170, 30, 140, 60]
    second = [110.0, 180, 40, 150, 70]  # halves differ by +10%, noise dwarfs it
    df = pd.DataFrame({"date": pd.date_range("2024-01-07", periods=10, freq="W"), "sales": first + second})
    [trend] = detect_trends(df)
    assert trend.change_pct > 5 and trend.p_value >= 0.05  # precondition
    assert trend.direction == "stable"
    assert "isn't statistically significant" in trend.message


def test_date_trend_rising_thirty_percent_is_up():
    [trend] = detect_trends(weekly_series(100, 130))
    assert trend.direction == "up"
    assert trend.change_pct == pytest.approx(30.0)


def test_date_trend_moving_two_percent_is_stable():
    [trend] = detect_trends(weekly_series(100, 102))
    assert trend.direction == "stable"


def test_row_order_trend_detects_a_rising_series():
    df = pd.DataFrame({"x": np.linspace(10, 30, 40)})
    [trend] = detect_trends(df)

    expected = (df["x"].iloc[-5:].mean() - df["x"].iloc[:5].mean()) / df["x"].iloc[:5].mean() * 100
    assert trend.direction == "up"
    assert trend.change_pct == pytest.approx(expected, abs=0.01)


def test_row_order_trend_detects_a_falling_series():
    df = pd.DataFrame({"x": np.linspace(30, 10, 40)})
    [trend] = detect_trends(df)
    assert trend.direction == "down"
    assert trend.change_pct < -10


def test_row_order_trend_ignores_small_moves_and_zero_baselines():
    df = pd.DataFrame({"flat": [100, 101, 99, 100, 102] * 4, "from_zero": [0] * 5 + [50] * 15})
    assert detect_trends(df) == []


def test_row_order_trend_is_skipped_when_a_date_column_exists():
    df = weekly_series(100, 130)
    assert [t.message for t in detect_trends(df) if "row order" in t.message] == []
