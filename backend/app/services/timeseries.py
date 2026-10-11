"""Time-series analysis for numeric columns measured over a date column.

Values are averaged into regular periods (daily, weekly, monthly, quarterly
or yearly, chosen from how far apart the dates are), then tested for
stationarity (ADF), autocorrelation, trend and seasonal strength
(classical decomposition), and projected forward with exponential smoothing
(Holt-Winters). The forecast band is approximate: it widens with the
horizon from the model's in-sample error.
"""

import math
import warnings

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app.models.schemas import ChartSpec, ForecastPoint, TimeSeriesAnalysis
from app.services.analysis import format_p
from app.services.timeaxis import TimeAxis, find_time_axis
from app.utils.json_compat import plotly_figure_to_dict

MAX_SERIES = 3
MIN_POINTS = 8
# Below this the ADF test has too little power to say anything either way.
MIN_ADF_POINTS = 20
MAX_POINTS = 1_000
SIGNIFICANCE = 0.05
Z_95 = 1.96

# (pandas frequency, label, seasonal period, rolling window, largest median gap in days)
FREQUENCIES = [
    ("D", "daily", 7, 7, 1.5),
    ("W", "weekly", 52, 4, 8),
    ("MS", "monthly", 12, 3, 35),
    ("QS", "quarterly", 4, 2, 100),
    ("YS", "yearly", None, 2, math.inf),
]


def analyze_time_series(df: pd.DataFrame, axis: TimeAxis | None = None) -> list[TimeSeriesAnalysis]:
    """Analyze up to MAX_SERIES numeric columns along the file's time axis (see timeaxis.py)."""
    if axis is None:
        axis = find_time_axis(df)
    if axis is None:
        return []
    numeric = [
        c
        for c in df.select_dtypes(include="number").columns
        if not pd.api.types.is_bool_dtype(df[c]) and str(c) not in axis.columns and df[c].nunique() > 1
    ]
    results = []
    for col in numeric[:MAX_SERIES]:
        frame = pd.DataFrame({"t": axis.values, "v": df[col]}).dropna()
        analysis = (_analyze_calendar if axis.is_calendar else _analyze_steps)(frame, axis.label, str(col))
        if analysis is not None:
            results.append(analysis)
    return results


def _choose_frequency(dates: pd.Series) -> tuple[str, str, int | None, int]:
    gaps = dates.sort_values().diff().dt.total_seconds().dropna() / 86_400
    median_gap = float(gaps[gaps > 0].median()) if (gaps > 0).any() else 1.0
    span_days = (dates.max() - dates.min()).total_seconds() / 86_400
    days = {"D": 1, "W": 7, "MS": 30.44, "QS": 91.3, "YS": 365.25}
    for freq, label, season, window, max_gap in FREQUENCIES:
        # Finer periods are skipped when they would make the series too long.
        if median_gap <= max_gap and span_days / days[freq] <= MAX_POINTS:
            return freq, label, season, window
    freq, label, season, window, _ = FREQUENCIES[-1]
    return freq, label, season, window


def _analyze_calendar(frame: pd.DataFrame, axis_label: str, col: str) -> TimeSeriesAnalysis | None:
    if frame["t"].nunique() < MIN_POINTS:
        return None
    freq, label, season, window = _choose_frequency(frame["t"])
    raw = frame.set_index("t")["v"].astype(float).resample(freq).mean()
    if raw.notna().sum() < MIN_POINTS:
        return None
    filled_gaps = int(raw.isna().sum())
    series = raw.interpolate(limit_direction="both")
    if series.nunique() < 2:
        return None
    seasonal_period = season if season and len(series) >= 2 * season else None

    def future(horizon: int) -> list[str]:
        return [d.date().isoformat() for d in pd.date_range(series.index[-1], periods=horizon + 1, freq=freq)[1:]]

    return _finish(series, col, axis_label, label, window, seasonal_period, filled_gaps, future)


def _analyze_steps(frame: pd.DataFrame, axis_label: str, col: str) -> TimeSeriesAnalysis | None:
    """A sequence without calendar dates: a step column, or the rows in file order."""
    series = frame.groupby("t")["v"].mean().astype(float)  # sorted by step, repeats averaged
    label = "step"
    if len(series) > MAX_POINTS:
        size = math.ceil(len(series) / MAX_POINTS)
        bucket = np.arange(len(series)) // size
        starts = pd.Series(series.index.to_numpy()).groupby(bucket).first().to_numpy()
        series = pd.Series(series.to_numpy()).groupby(bucket).mean()
        series.index = pd.Index(starts)
        label = f"{size}-step"
    if len(series) < MIN_POINTS or series.nunique() < 2:
        return None
    # Without a calendar, a repeating pattern is read from the autocorrelation itself.
    seasonal_period = _repeat_length(series)
    window = max(3, min(20, len(series) // 20))
    step = float(np.median(np.diff(series.index.to_numpy(dtype=float)))) or 1.0
    last = float(series.index[-1])

    def future(horizon: int) -> list[str]:
        return [f"{last + h * step:g}" for h in range(1, horizon + 1)]

    return _finish(series, col, axis_label, label, window, seasonal_period, 0, future)


def _finish(series, col, axis_label, label, window, seasonal_period, filled_gaps, future) -> TimeSeriesAnalysis:
    adf_stat, adf_p = _adf(series)
    lag, lag_acf = _strongest_lag(series, seasonal_period)
    seasonal_strength, trend_strength, decomposition = _decompose(series, seasonal_period)
    horizon = max(1, min(seasonal_period or 6, len(series) // 4, 12))
    method, forecast = _forecast(series, seasonal_period, horizon, future(horizon))

    rolling = series.rolling(window, min_periods=1).mean()
    charts = [_forecast_chart(series, rolling, window, forecast, col, label, axis_label), _acf_chart(series, col)]
    if decomposition is not None:
        charts.append(_decomposition_chart(decomposition, col))

    analysis = TimeSeriesAnalysis(
        column=col,
        date_column=axis_label,
        frequency=label,
        points=len(series),
        filled_gaps=filled_gaps,
        rolling_window=window,
        adf_statistic=adf_stat,
        adf_p=adf_p,
        stationary=None if adf_p is None else adf_p < SIGNIFICANCE,
        strongest_lag=lag,
        strongest_lag_acf=lag_acf,
        seasonal_period=seasonal_period,
        seasonal_strength=seasonal_strength,
        trend_strength=trend_strength,
        forecast_method=method,
        forecast=forecast,
        charts=charts,
        summary="",
    )
    analysis.summary = _summary(analysis)
    return analysis


def _finite(value) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def _adf(series: pd.Series) -> tuple[float | None, float | None]:
    from statsmodels.tsa.stattools import adfuller

    if len(series) < MIN_ADF_POINTS:
        return None, None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = adfuller(series.to_numpy(), autolag="AIC")
    except (ValueError, np.linalg.LinAlgError):
        return None, None
    return _finite(result[0]), _finite(result[1])


def _strongest_lag(series: pd.Series, season: int | None) -> tuple[int | None, float | None]:
    from statsmodels.tsa.stattools import acf

    max_lag = min(len(series) // 2 - 1, (season or 6) * 2, 60)
    if max_lag < 1:
        return None, None
    values = acf(series.to_numpy(), nlags=max_lag, fft=True)
    # Beyond roughly 2 / sqrt(n), an autocorrelation is unlikely to be chance.
    threshold = Z_95 / math.sqrt(len(series))
    lags = [(lag, float(values[lag])) for lag in range(1, max_lag + 1) if abs(values[lag]) > threshold]
    if not lags:
        return None, None
    lag, value = max(lags, key=lambda item: abs(item[1]))
    return lag, round(value, 4)


def _repeat_length(series: pd.Series) -> int | None:
    """The lag of the highest positive autocorrelation peak, if it's clear (0.3+) and seen twice."""
    from statsmodels.tsa.stattools import acf

    max_lag = min(len(series) // 2, 60)
    if max_lag < 3:
        return None
    values = acf(series.to_numpy(), nlags=max_lag, fft=True)
    # A peak, not just a high value: a slow trend keeps every early lag high.
    peaks = [
        lag
        for lag in range(2, max_lag)
        if values[lag] >= 0.3 and values[lag] > values[lag - 1] and values[lag] >= values[lag + 1]
    ]
    if not peaks:
        return None
    best = max(peaks, key=lambda lag: values[lag])
    return best if len(series) >= 2 * best else None


def _decompose(series: pd.Series, period: int | None):
    """Seasonal and trend strength (Hyndman's measures, 0 to 1) and the components for a chart."""
    if period is None:
        return None, None, None
    from statsmodels.tsa.seasonal import seasonal_decompose

    parts = seasonal_decompose(series, model="additive", period=period, extrapolate_trend="period")
    resid, seasonal, trend = parts.resid.dropna(), parts.seasonal, parts.trend
    seasonal_strength = max(0.0, 1 - resid.var() / (seasonal + parts.resid).dropna().var())
    trend_strength = max(0.0, 1 - resid.var() / (trend + parts.resid).dropna().var())
    return round(float(seasonal_strength), 4), round(float(trend_strength), 4), parts


def _forecast(
    series: pd.Series, period: int | None, horizon: int, labels: list[str]
) -> tuple[str, list[ForecastPoint]]:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    seasonal = "add" if period else None
    method = "Holt-Winters exponential smoothing (trend and seasonality)" if period else "Holt's linear trend"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(
                series.to_numpy(), trend="add", damped_trend=True, seasonal=seasonal, seasonal_periods=period
            ).fit()
            values = fit.forecast(horizon)
    except (ValueError, np.linalg.LinAlgError):
        return "not enough data to forecast", []
    sigma = float(np.std(series.to_numpy() - fit.fittedvalues, ddof=1))
    return method, [
        ForecastPoint(
            date=d,
            value=round(float(v), 4),
            lower=round(float(v - Z_95 * sigma * math.sqrt(h)), 4),
            upper=round(float(v + Z_95 * sigma * math.sqrt(h)), 4),
        )
        for h, (d, v) in enumerate(zip(labels, values, strict=True), start=1)
    ]


def _forecast_chart(series, rolling, window, forecast, col, label, axis_label) -> ChartSpec:
    fig = go.Figure()
    markers = "lines+markers" if len(series) <= 120 else "lines"
    fig.add_trace(go.Scatter(x=series.index, y=series.values, name=f"{label} average", mode=markers))
    fig.add_trace(go.Scatter(x=rolling.index, y=rolling.values, name=f"{window}-period rolling mean", mode="lines"))
    if forecast:
        xs = [p.date for p in forecast]
        fig.add_trace(
            go.Scatter(
                x=xs, y=[p.upper for p in forecast], mode="lines", line={"width": 0}, showlegend=False, hoverinfo="skip"
            )
        )
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=[p.lower for p in forecast],
                mode="lines",
                line={"width": 0},
                fill="tonexty",
                name="approx. 95% range",
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(x=xs, y=[p.value for p in forecast], name="forecast", mode="lines", line={"dash": "dash"})
        )
    fig.update_layout(title=f"{col}: history and forecast", legend={"orientation": "h"}, xaxis_title=axis_label)
    return ChartSpec(
        id=f"ts_{col}", title=f"{col}: history and forecast", chart_type="line", plotly_json=plotly_figure_to_dict(fig)
    )


def _acf_chart(series: pd.Series, col: str) -> ChartSpec:
    from statsmodels.tsa.stattools import acf

    max_lag = max(1, min(len(series) // 2 - 1, 40))
    values = acf(series.to_numpy(), nlags=max_lag, fft=True)[1:]
    band = Z_95 / math.sqrt(len(series))
    lags = list(range(1, max_lag + 1))
    fig = go.Figure(go.Bar(x=lags, y=values, name="autocorrelation"))
    for y in (band, -band):
        fig.add_hline(y=y, line_dash="dot", line_width=1)
    fig.update_layout(
        title=f"{col}: autocorrelation by lag", xaxis_title="lag (periods)", yaxis_title="ACF", showlegend=False
    )
    return ChartSpec(
        id=f"ts_acf_{col}", title=f"{col}: autocorrelation", chart_type="bar", plotly_json=plotly_figure_to_dict(fig)
    )


def _decomposition_chart(parts, col: str) -> ChartSpec:
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, subplot_titles=["Trend", "Seasonal pattern", "Remainder"])
    for row, component in enumerate([parts.trend, parts.seasonal, parts.resid], start=1):
        fig.add_trace(go.Scatter(x=component.index, y=component.values, mode="lines", showlegend=False), row=row, col=1)
    fig.update_layout(title=f"{col}: trend, season and remainder")
    return ChartSpec(
        id=f"ts_decomp_{col}",
        title=f"{col}: trend, season and remainder",
        chart_type="line",
        plotly_json=plotly_figure_to_dict(fig),
    )


def _summary(a: TimeSeriesAnalysis) -> str:
    unit = "periods" if a.frequency not in ("step",) and not a.frequency.endswith("-step") else "steps"
    parts = [f"'{a.column}' over {a.date_column}: {a.points} {a.frequency} {unit}"]
    if a.filled_gaps:
        parts[-1] += f" ({a.filled_gaps} without data were filled in between neighbours for these tests)"
    parts[-1] += "."
    if a.stationary is True:
        parts.append(f"It moves around a stable level (ADF {format_p(a.adf_p)}), so past averages are a fair guide.")
    elif a.stationary is False:
        # Not rejecting the null isn't proof of drift, so this stays a hedge.
        parts.append(
            f"The test can't confirm it returns to a stable level (ADF {format_p(a.adf_p)}); "
            "it may drift, so averages over the whole period could mislead."
        )
    else:
        parts.append(f"There are too few periods (under {MIN_ADF_POINTS}) to test whether its level is stable.")
    if a.seasonal_strength is not None:
        if a.seasonal_strength >= 0.6:
            parts.append(f"It has a strong repeating pattern every {a.seasonal_period} periods.")
        elif a.seasonal_strength >= 0.3:
            parts.append(f"It has a moderate repeating pattern every {a.seasonal_period} periods.")
    if a.strongest_lag is not None and a.strongest_lag_acf is not None:
        direction = "follows" if a.strongest_lag_acf > 0 else "tends to reverse"
        parts.append(
            f"Each value {direction} the one {a.strongest_lag} period(s) earlier "
            f"(autocorrelation {a.strongest_lag_acf:.2f})."
        )
    if a.forecast:
        last = a.forecast[-1]
        parts.append(
            f"A {a.forecast_method} projection puts it near {last.value:,.2f} by {last.date} "
            f"(roughly {last.lower:,.2f} to {last.upper:,.2f})."
        )
    return " ".join(parts)
