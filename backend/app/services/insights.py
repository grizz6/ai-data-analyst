import pandas as pd

from app.models.schemas import (
    CategoricalSummary,
    CorrelationPair,
    NumericSummary,
    QualityIssue,
    RuleInsight,
    TrendInsight,
)


def generate_rule_insights(
    df: pd.DataFrame,
    quality_issues: list[QualityIssue],
    numeric_summaries: list[NumericSummary],
    categorical_summaries: list[CategoricalSummary],
    correlations: list[CorrelationPair],
    trends: list[TrendInsight],
) -> list[RuleInsight]:
    insights: list[RuleInsight] = []

    insights.append(
        RuleInsight(
            category="overview",
            title="Dataset size",
            message=f"The dataset has {len(df):,} rows and {len(df.columns)} columns after cleaning.",
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
                message=f"Found {len(warnings)} warning(s) such as high missingness or duplicates.",
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
                message=f"'{top['value']}' is most frequent ({top['count']:,} rows, ~{share:.0f}% of shown top values).",
            )
        )

    for pair in correlations[:3]:
        strength = "strong" if abs(pair.correlation) >= 0.7 else "moderate"
        direction = "positive" if pair.correlation > 0 else "negative"
        insights.append(
            RuleInsight(
                category="correlation",
                title="Correlated columns",
                message=(
                    f"{strength.capitalize()} {direction} correlation ({pair.correlation}) "
                    f"between '{pair.column_a}' and '{pair.column_b}'."
                ),
            )
        )

    for trend in trends[:4]:
        insights.append(
            RuleInsight(
                category="trend",
                title=f"Trend in {trend.column}",
                message=trend.message,
            )
        )

    numeric_cols = df.select_dtypes(include="number").columns
    for col in numeric_cols[:3]:
        top_idx = df[col].idxmax()
        if pd.isna(top_idx):
            continue
        val = df.loc[top_idx, col]
        insights.append(
            RuleInsight(
                category="extrema",
                title=f"Highest {col}",
                message=f"Maximum {col} is {val} (row index {top_idx}).",
            )
        )

    return insights
