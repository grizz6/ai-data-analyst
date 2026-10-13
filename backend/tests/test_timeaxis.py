import numpy as np
import pandas as pd
import pytest

from app.services.pipeline import compute_analysis
from app.services.timeaxis import find_time_axis
from app.services.timeseries import analyze_time_series

rng = np.random.default_rng(8)


def ar1(n: int, phi: float = 0.9) -> np.ndarray:
    values = [0.0]
    for _ in range(n - 1):
        values.append(phi * values[-1] + rng.normal())
    return np.array(values)


def test_a_parsed_date_column_comes_first():
    df = pd.DataFrame({"when": pd.date_range("2024-01-01", periods=20), "year": 2024, "v": range(20)})
    axis = find_time_axis(df)
    assert (axis.kind, axis.columns) == ("dates", ["when"])


def test_year_and_month_columns_are_combined():
    years = np.repeat([2021, 2022, 2023], 12)
    months = np.tile(range(1, 13), 3)
    axis = find_time_axis(pd.DataFrame({"Year": years, "Month": months, "sales": rng.normal(100, 5, 36)}))
    assert (axis.kind, axis.label) == ("date_parts", "Year + Month")
    assert axis.values.iloc[13] == pd.Timestamp("2022-02-01")


def test_month_names_and_day_and_hour():
    df = pd.DataFrame(
        {
            "year": [2024] * 10,
            "month": ["Jan"] * 5 + ["February"] * 5,
            "day": [1, 2, 3, 4, 5] * 2,
            "hour": range(10),
            "v": range(10),
        }
    )
    axis = find_time_axis(df)
    assert axis.columns == ["year", "month", "day", "hour"]
    assert axis.values.iloc[6] == pd.Timestamp("2024-02-02 06:00")


def test_year_and_quarter():
    df = pd.DataFrame({"yr": np.repeat([2020, 2021, 2022], 4), "qtr": ["Q1", "Q2", "Q3", "Q4"] * 3, "v": range(12)})
    axis = find_time_axis(df)
    assert axis.kind == "date_parts" and axis.values.iloc[5] == pd.Timestamp("2021-04-01")


@pytest.mark.parametrize("unit, scale", [("seconds", 1), ("milliseconds", 1_000)])
def test_unix_timestamps_by_name(unit, scale):
    start = 1_700_000_000
    stamps = (start + rng.permutation(np.arange(50)) * 3_600) * scale  # shuffled, so only the name gives it away
    axis = find_time_axis(pd.DataFrame({"created_at": stamps, "v": rng.normal(size=50)}))
    assert axis.kind == "epoch" and unit in axis.label
    assert axis.values.min() == pd.Timestamp(start, unit="s")


def test_increasing_numbers_in_epoch_range_count_even_without_a_time_name():
    stamps = 1_700_000_000 + np.arange(40) * 60
    assert find_time_axis(pd.DataFrame({"logged": stamps, "v": rng.normal(size=40)})).kind == "epoch"


def test_ids_that_happen_to_be_in_epoch_range_are_not_times():
    ids = rng.permutation(np.arange(1_700_000_000, 1_700_000_040))
    axis = find_time_axis(pd.DataFrame({"account": ids, "v": rng.normal(size=40)}))
    assert axis is None


def test_a_year_column_alone():
    df = pd.DataFrame({"year": range(1990, 2020), "population": np.linspace(1, 2, 30)})
    axis = find_time_axis(df)
    assert axis.kind == "year" and axis.values.iloc[0] == pd.Timestamp("1990-01-01")


def test_a_step_column():
    df = pd.DataFrame({"step": range(0, 200, 2), "loss": np.exp(-np.arange(100) / 30)})
    axis = find_time_axis(df)
    assert (axis.kind, axis.columns) == ("step_column", ["step"])


def test_row_order_when_rows_depend_on_the_ones_before():
    df = pd.DataFrame({"reading": ar1(200), "other": rng.normal(size=200)})
    assert find_time_axis(df).kind == "row_order"


def test_independent_rows_have_no_time_axis():
    assert find_time_axis(pd.DataFrame({"a": rng.normal(size=200), "b": rng.normal(size=200)})) is None


def test_a_file_sorted_by_a_value_is_not_a_sequence():
    df = pd.DataFrame({"price": np.sort(rng.normal(size=200)), "qty": rng.normal(size=200)})
    df["qty"] = df["price"] * 2 + rng.normal(0, 0.1, 200)  # tracks the sorted column, so looks serially dependent
    assert find_time_axis(df) is None


def test_rows_grouped_by_category_are_not_a_sequence():
    group = np.repeat(["a", "b", "c", "d"], 50)
    value = np.select([group == "a", group == "b", group == "c"], [0, 10, 20], 30) + rng.normal(size=200)
    assert find_time_axis(pd.DataFrame({"group": group, "value": value})) is None


def test_step_series_are_analyzed_in_steps():
    df = pd.DataFrame(
        {"t": np.arange(150), "signal": 10 * np.sin(2 * np.pi * np.arange(150) / 12) + rng.normal(0, 1, 150)}
    )
    (ts,) = analyze_time_series(df)
    assert ts.date_column == "t" and ts.frequency == "step"
    assert ts.seasonal_period == 12 and ts.seasonal_strength > 0.8
    assert [c.id for c in ts.charts] == ["ts_signal", "ts_acf_signal", "ts_decomp_signal"]


def test_long_row_order_is_averaged_into_buckets():
    df = pd.DataFrame({"reading": ar1(3_000)})
    (ts,) = analyze_time_series(df)
    assert ts.date_column == "row order"
    assert ts.points <= 1_000 and ts.frequency == "3-step"


def test_pipeline_uses_date_parts_and_does_not_analyze_them_as_values():
    years = np.repeat([2021, 2022, 2023], 12)
    months = np.tile(range(1, 13), 3)
    csv = pd.DataFrame({"year": years, "month": months, "sales": rng.normal(100, 5, 36)}).to_csv(index=False).encode()
    result = compute_analysis(csv, "monthly.csv")
    assert result.time_axis.label == "year + month"
    assert [t.column for t in result.time_series] == ["sales"]
    assert result.time_series[0].frequency == "monthly"


def test_rows_over_time_chart_for_each_span():
    for periods, freq in ((60, "D"), (400, "D"), (100, "MS")):
        dates = pd.date_range("2020-01-01", periods=periods, freq=freq)
        csv = pd.DataFrame({"when": dates.astype(str), "v": rng.normal(size=periods)}).to_csv(index=False).encode()
        result = compute_analysis(csv, "t.csv")
        assert "rows_over_time" in [c.id for c in result.visuals["explore"]]
