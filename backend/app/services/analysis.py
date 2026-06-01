import pandas as pd

from app.models.schemas import (
    CategoricalSummary,
    CorrelationPair,
    NumericSummary,
    TrendInsight,
)


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

    corr = numeric.corr(numeric_only=True)
    pairs: list[CorrelationPair] = []

    cols = list(corr.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1 :]:
            value = corr.loc[a, b]
            if pd.isna(value) or abs(value) < min_abs:
                continue
            pairs.append(
                CorrelationPair(
                    column_a=str(a),
                    column_b=str(b),
                    correlation=round(float(value), 4),
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
            change_pct = ((second_half - first_half) / abs(first_half)) * 100
            direction = "up" if change_pct > 5 else "down" if change_pct < -5 else "stable"
            trends.append(
                TrendInsight(
                    column=str(num_col),
                    direction=direction,
                    change_pct=round(float(change_pct), 2),
                    message=(
                        f"'{num_col}' trended {direction} (~{change_pct:+.1f}%) "
                        f"comparing first vs second half of the timeline in '{date_col}'."
                    ),
                )
            )

    for col in numeric_cols[:5]:
        series = df[col].dropna()
        if len(series) < 10:
            continue
        rolling = series.rolling(window=min(5, len(series)), min_periods=2).mean()
        if rolling.iloc[-1] > rolling.iloc[0] * 1.1:
            trends.append(
                TrendInsight(
                    column=str(col),
                    direction="up",
                    change_pct=None,
                    message=f"'{col}' shows an upward pattern over row order (proxy trend).",
                )
            )
        elif rolling.iloc[-1] < rolling.iloc[0] * 0.9:
            trends.append(
                TrendInsight(
                    column=str(col),
                    direction="down",
                    change_pct=None,
                    message=f"'{col}' shows a downward pattern over row order (proxy trend).",
                )
            )

    return trends[:8]


def _safe_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 4)
