from collections.abc import Collection

import pandas as pd

from app.models.schemas import (
    CategoricalSummary,
    CorrelationPair,
    NumericSummary,
    QualityIssue,
    RuleInsight,
    TrendInsight,
)
from app.services.analysis import SIGNIFICANCE_LEVEL, format_p


def generate_rule_insights(
    df: pd.DataFrame,
    quality_issues: list[QualityIssue],
    numeric_summaries: list[NumericSummary],
    categorical_summaries: list[CategoricalSummary],
    correlations: list[CorrelationPair],
    trends: list[TrendInsight],
    identifiers: Collection[str] = (),
) -> list[RuleInsight]:
    insights: list[RuleInsight] = []
    present_ids = [c for c in identifiers if c in df.columns]

    insights.append(
        RuleInsight(
            category="overview",
            title="Dataset size",
            message=f"The dataset has {len(df):,} rows and {len(df.columns)} columns after cleaning.",
        )
    )
    if present_ids:
        names = ", ".join(f"'{c}'" for c in present_ids)
        insights.append(
            RuleInsight(
                category="overview",
                title="Identifier columns",
                message=f"{names} looked like identifiers, so they were left out of statistics and charts.",
            )
        )

    errors = [q for q in quality_issues if q.severity == "error"]
    warnings = [q for q in quality_issues if q.severity == "warning"]
    if errors:
        insights.append(
            RuleInsight(
                category="quality",
                title="Critical data quality issues",
                message=f"Found {len(errors)} critical issue(s) before cleaning. Review the quality panel.",
                severity="error",
            )
        )
    if warnings:
        insights.append(
            RuleInsight(
                category="quality",
                title="Data quality warnings",
                message=f"Found {len(warnings)} warning(s) before cleaning. The data quality panel lists each one.",
                severity="warning",
            )
        )

    for summary in numeric_summaries[:5]:
        if summary.mean is not None and summary.max is not None:
            spread = summary.max - (summary.min or 0)
            insights.append(
                RuleInsight(
                    category="numeric",
                    title=f"Summary for {summary.column}",
                    message=(
                        f"Mean {summary.mean:,.2f}, median {summary.median:,.2f}, "
                        f"range {summary.min:,.2f} – {summary.max:,.2f} (spread {spread:,.2f})."
                    ),
                )
            )

    for cat in categorical_summaries[:3]:
        if not cat.top_values:
            continue
        top = cat.top_values[0]
        total_top = sum(v["count"] for v in cat.top_values)
        share = (top["count"] / total_top) * 100 if total_top else 0
        insights.append(
            RuleInsight(
                category="categorical",
                title=f"Top category in {cat.column}",
                message=(
                    f"'{top['value']}' is most frequent "
                    f"({top['count']:,} rows, ~{share:.0f}% of shown top values)."
                ),
            )
        )

    for pair in correlations[:3]:
        strength = "strong" if abs(pair.correlation) >= 0.7 else "moderate"
        direction = "positive" if pair.correlation > 0 else "negative"
        evidence = f", n = {pair.n}, {format_p(pair.p_value)}" if pair.n else ""
        message = (
            f"{strength.capitalize()} {direction} correlation ({pair.correlation}{evidence}) "
            f"between '{pair.column_a}' and '{pair.column_b}'."
        )
        if pair.p_value is not None and pair.p_value >= SIGNIFICANCE_LEVEL:
            message += f" With only {pair.n} rows this could be chance, so don't rely on it yet."
        insights.append(RuleInsight(category="correlation", title="Correlated columns", message=message))

    for trend in trends[:4]:
        insights.append(
            RuleInsight(
                category="trend",
                title=f"Trend in {trend.column}",
                message=trend.message,
            )
        )

    numeric_cols = [c for c in df.select_dtypes(include="number").columns if c not in identifiers]
    for col in numeric_cols[:3]:
        if df[col].isna().all():
            continue
        top_idx = df[col].idxmax()
        val = df.loc[top_idx, col]
        insights.append(
            RuleInsight(
                category="extrema",
                title=f"Highest {col}",
                message=f"Maximum {col} is {val} ({_locate_row(df, top_idx, present_ids)}).",
            )
        )

    return insights


def _locate_row(df: pd.DataFrame, idx, identifiers: list[str]) -> str:
    """Point at a record the way a reader would find it in their own file."""
    if identifiers:
        value = df.loc[idx, identifiers[0]]
        # A gap elsewhere in an integer ID column turns it into floats; show 1017, not 1017.0.
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return f"{identifiers[0]} {value}"
    if pd.api.types.is_integer(idx):
        # Index 0 is the first data row, which sits under the header on row 2.
        return f"row {int(idx) + 2} of the file"
    return f"row {idx}"
