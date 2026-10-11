import numpy as np
import pandas as pd

from app.services.timeseries import analyze_time_series

rng = np.random.default_rng(3)


def daily(values, start="2023-01-01") -> pd.DataFrame:
    return pd.DataFrame({"day": pd.date_range(start, periods=len(values), freq="D"), "v": values})


def test_weekly_cycle_in_daily_data_is_found_and_forecast():
    n = 140
    weekly = 10 * np.sin(2 * np.pi * np.arange(n) / 7)
    (ts,) = analyze_time_series(daily(100 + weekly + rng.normal(0, 1, n)))

    assert (ts.frequency, ts.points, ts.seasonal_period) == ("daily", n, 7)
    assert ts.seasonal_strength > 0.8
    assert ts.forecast_method.startswith("Holt-Winters")
    assert len(ts.forecast) == 7
    assert [c.id for c in ts.charts] == ["ts_v", "ts_acf_v", "ts_decomp_v"]
    assert "strong repeating pattern every 7 periods" in ts.summary


def test_forecast_band_contains_the_forecast_and_widens():
    (ts,) = analyze_time_series(daily(np.arange(60, dtype=float) + rng.normal(0, 2, 60)))
    assert all(p.lower < p.value < p.upper for p in ts.forecast)
    widths = [p.upper - p.lower for p in ts.forecast]
    assert widths == sorted(widths) and widths[-1] > widths[0]
    assert ts.forecast[0].value > 55  # carries the upward trend on


def test_stationarity_white_noise_versus_random_walk():
    (noise,) = analyze_time_series(daily(rng.normal(0, 1, 300)))
    (walk,) = analyze_time_series(daily(np.cumsum(rng.normal(0, 1, 300))))
    assert noise.stationary is True
    assert walk.stationary is False
    assert "can't confirm it returns to a stable level" in walk.summary


def test_short_series_skip_the_stationarity_test():
    (ts,) = analyze_time_series(daily(rng.normal(0, 1, 12)))
    assert ts.adf_p is None and ts.stationary is None
    assert "too few periods" in ts.summary


def test_autocorrelation_at_lag_one():
    values = [0.0]
    for _ in range(299):
        values.append(0.9 * values[-1] + rng.normal())
    (ts,) = analyze_time_series(daily(values))
    assert ts.strongest_lag == 1 and ts.strongest_lag_acf > 0.7


def test_irregular_dates_are_grouped_monthly_with_gaps_filled():
    dates = pd.to_datetime(
        ["2023-01-03", "2023-01-20", "2023-02-14", "2023-04-02", "2023-04-28", "2023-05-15"]
        + ["2023-06-09", "2023-06-30", "2023-07-21", "2023-08-11", "2023-09-01", "2023-09-22"]
    )
    df = pd.DataFrame({"when": dates, "v": np.arange(12, dtype=float)})
    (ts,) = analyze_time_series(df)
    assert ts.frequency == "monthly"
    assert ts.filled_gaps == 1  # March had no data
    assert "1 without data were filled" in ts.summary


def test_nothing_to_analyze():
    assert analyze_time_series(pd.DataFrame({"v": range(50)})) == []  # no dates
    assert analyze_time_series(daily([1.0, 2.0, 3.0])) == []  # too few points
    assert analyze_time_series(daily([5.0] * 40)) == []  # constant


def test_time_series_reach_the_api(client, sample_csv_bytes):
    body = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")}).json()
    columns = [t["column"] for t in body["time_series"]]
    assert columns == ["sales", "units"]
    assert body["time_series"][0]["charts"][0]["plotly_json"]["data"]


def test_long_fine_grained_data_is_grouped_to_a_readable_length():
    hours = pd.date_range("2021-01-01", "2023-12-31", freq="h")  # 3 years: daily would be 1,095 points
    (ts,) = analyze_time_series(pd.DataFrame({"t": hours, "v": rng.normal(0, 1, len(hours))}))
    assert ts.frequency == "weekly"
    assert ts.points <= 1_000


def test_data_spanning_too_short_a_time_is_skipped():
    minutes = pd.date_range("2024-01-01", periods=2_000, freq="min")  # under two days
    assert analyze_time_series(pd.DataFrame({"t": minutes, "v": rng.normal(0, 1, 2_000)})) == []


def test_report_shows_time_series_with_their_charts(client, sample_csv_bytes):
    upload = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")})
    html = client.get(f"/api/sessions/{upload.json()['session_id']}/report").text
    assert "<h2>Time series</h2>" in html
    assert "sales: history and forecast" in html
