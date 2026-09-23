import math
from dataclasses import dataclass

import pandas as pd
from scipy import stats

from app.models.schemas import (
    CategoricalSummary,
    CorrelationPair,
    NumericSummary,
    TrendInsight,
)

SIGNIFICANCE_LEVEL = 0.05
# A trend is reported as up or down only if it is both big enough to matter
# (practical) and unlikely to be noise (statistical). Either alone is not enough.
DATE_TREND_MIN_CHANGE_PCT = 5.0
ROW_TREND_MIN_CHANGE_PCT = 10.0
DAYS_PER_MONTH = 30.44
# Timelines longer than this report the slope per month instead of per day.
DAILY_SLOPE_MAX_SPAN_DAYS = 90


def format_p(p: float | None) -> str:
    """'p < 0.001' or 'p = 0.042', the way results are usually written."""
    if p is None:
        return "p n/a"
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


@dataclass
class LineFit:
    slope: float
    p_value: float


def _fit_line(x: pd.Series, y: pd.Series) -> LineFit | None:
    """Least-squares line through (x, y); None when a line can't be fitted."""
    if len(x) < 3 or x.nunique() < 2:
        return None
    if y.nunique() < 2:
        return LineFit(slope=0.0, p_value=1.0)
    result = stats.linregress(x.to_numpy(dtype=float), y.to_numpy(dtype=float))
    return LineFit(slope=float(result.slope), p_value=float(result.pvalue))


def numeric_summaries(df: pd.DataFrame) -> list[NumericSummary]:
    summaries: list[NumericSummary] = []
    for col in df.select_dtypes(include="number").columns:
        series = df[col].dropna()
        if series.empty:
            continue
        desc = series.describe()
        summaries.append(
            NumericSummary(
                column=str(col),
                count=int(desc.get("count", 0)),
                mean=_safe_float(desc.get("mean")),
                std=_safe_float(desc.get("std")),
                min=_safe_float(desc.get("min")),
                q25=_safe_float(desc.get("25%")),
                median=_safe_float(desc.get("50%")),
                q75=_safe_float(desc.get("75%")),
                max=_safe_float(desc.get("max")),
            )
        )
    return summaries


def categorical_summaries(df: pd.DataFrame, top_n: int = 8) -> list[CategoricalSummary]:
    summaries: list[CategoricalSummary] = []
    for col in df.select_dtypes(exclude="number").columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        counts = df[col].value_counts(dropna=True).head(top_n)
        if counts.empty:
            continue
        summaries.append(
            CategoricalSummary(
                column=str(col),
                top_values=[
                    {"value": str(idx), "count": int(val)}
                    for idx, val in counts.items()
                ],
            )
        )
    return summaries


def top_correlations(df: pd.DataFrame, min_abs: float = 0.5, limit: int = 10) -> list[CorrelationPair]:
    numeric = df.select_dtypes(include="number")
    if numeric.shape[1] < 2:
        return []

    # The full matrix is cheap; p-values are computed only for pairs that pass the cut.
    corr = numeric.corr(numeric_only=True)
    pairs: list[CorrelationPair] = []

    cols = list(corr.columns)
    matrix = corr.to_numpy(dtype=float)
    for i, a in enumerate(cols):
        for j in range(i + 1, len(cols)):
            b = cols[j]
            value = float(matrix[i, j])  # NaN when a column is constant
            if math.isnan(value) or abs(value) < min_abs:
                continue
            both = numeric[[a, b]].dropna()
            if len(both) < 3:
                continue
            r, p = stats.pearsonr(both[a], both[b])
            pairs.append(
                CorrelationPair(
                    column_a=str(a),
                    column_b=str(b),
                    correlation=round(float(r), 4),
                    n=len(both),
                    p_value=float(p),
                )
            )

    pairs.sort(key=lambda p: abs(p.correlation), reverse=True)
    return pairs[:limit]


def detect_trends(df: pd.DataFrame) -> list[TrendInsight]:
    trends: list[TrendInsight] = []
    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    numeric_cols = list(df.select_dtypes(include="number").columns)

    for date_col in date_cols[:1]:
        ordered = df.dropna(subset=[date_col]).sort_values(date_col)
        for num_col in numeric_cols[:3]:
            series = ordered[[date_col, num_col]].dropna()
            if len(series) < 3:
                continue
            first_half = series[num_col].iloc[: len(series) // 2].mean()
            second_half = series[num_col].iloc[len(series) // 2 :].mean()
            if first_half == 0 or pd.isna(first_half) or pd.isna(second_half):
                continue
            change_pct = float(((second_half - first_half) / abs(first_half)) * 100)

            days = (series[date_col] - series[date_col].iloc[0]).dt.total_seconds() / 86_400
            fit = _fit_line(days, series[num_col])
            if fit is None:
                continue
            unit, days_per_unit = (
                ("day", 1.0) if days.iloc[-1] <= DAILY_SLOPE_MAX_SPAN_DAYS else ("month", DAYS_PER_MONTH)
            )
            slope = fit.slope * days_per_unit
            significant = fit.p_value < SIGNIFICANCE_LEVEL

            if significant and change_pct > DATE_TREND_MIN_CHANGE_PCT:
                direction = "up"
            elif significant and change_pct < -DATE_TREND_MIN_CHANGE_PCT:
                direction = "down"
            else:
                direction = "stable"

            fit_text = f"fitted slope {slope:+.4g} per {unit}, {format_p(fit.p_value)}"
            if direction != "stable":
                message = (
                    f"'{num_col}' trended {direction} over '{date_col}': the second half averaged "
                    f"{change_pct:+.1f}% versus the first ({fit_text})."
                )
            elif abs(change_pct) > DATE_TREND_MIN_CHANGE_PCT:
                message = (
                    f"'{num_col}' moved {change_pct:+.1f}% between the halves of '{date_col}', "
                    f"but the trend isn't statistically significant ({fit_text}), so treat it as stable."
                )
            else:
                message = (
                    f"'{num_col}' was stable over '{date_col}' ({change_pct:+.1f}% between halves, {fit_text})."
                )

            trends.append(
                TrendInsight(
                    column=str(num_col),
                    direction=direction,
                    change_pct=round(change_pct, 2),
                    message=message,
                    slope=round(slope, 6),
                    slope_unit=unit,
                    p_value=fit.p_value,
                )
            )

    # Row order is only a stand-in for time when there is no real date column.
    if date_cols:
        return trends[:8]

    window = 5
    for col in numeric_cols[:5]:
        values = df[col].dropna().reset_index(drop=True)
        if len(values) < 2 * window:
            continue
        start = values.iloc[:window].mean()
        end = values.iloc[-window:].mean()
        if start == 0:
            continue
        change_pct = float(((end - start) / abs(start)) * 100)
        fit = _fit_line(pd.Series(range(len(values)), dtype=float), values)
        if abs(change_pct) <= ROW_TREND_MIN_CHANGE_PCT or fit is None or fit.p_value >= SIGNIFICANCE_LEVEL:
            continue
        direction = "up" if change_pct > 0 else "down"
        pattern = "an upward" if direction == "up" else "a downward"
        trends.append(
            TrendInsight(
                column=str(col),
                direction=direction,
                change_pct=round(change_pct, 2),
                message=(
                    f"'{col}' shows {pattern} pattern over row order "
                    f"(~{change_pct:+.1f}%, first {window} rows vs last {window}; "
                    f"fitted slope {fit.slope:+.4g} per row, {format_p(fit.p_value)}). "
                    "No date column was found, so row order stands in for time."
                ),
                slope=round(fit.slope, 6),
                slope_unit="row",
                p_value=fit.p_value,
            )
        )

    return trends[:8]


def _safe_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)
