import pandas as pd

from app.models.schemas import QualityIssue


def check_quality(df: pd.DataFrame) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    n = len(df)

    dup_count = int(df.duplicated().sum())
    if dup_count > 0:
        issues.append(
            QualityIssue(
                severity="warning",
                category="duplicates",
                message=f"Found {dup_count} duplicate row(s) ({round(dup_count / n * 100, 2)}% of rows).",
                details={"duplicate_rows": dup_count},
            )
        )

    if n == 0:
        issues.append(
            QualityIssue(
                severity="error",
                category="empty",
                message="Dataset has no rows.",
            )
        )
        return issues

    for col in df.columns:
        null_pct = df[col].isna().mean() * 100
        if null_pct >= 50:
            issues.append(
                QualityIssue(
                    severity="warning" if null_pct < 90 else "error",
                    category="missing",
                    column=str(col),
                    message=f"Column '{col}' is {null_pct:.1f}% missing.",
                    details={"null_pct": round(null_pct, 2)},
                )
            )
        elif null_pct > 0:
            issues.append(
                QualityIssue(
                    severity="info",
                    category="missing",
                    column=str(col),
                    message=f"Column '{col}' has {null_pct:.1f}% missing values.",
                    details={"null_pct": round(null_pct, 2)},
                )
            )

        if df[col].nunique(dropna=True) == 1 and df[col].notna().any():
            issues.append(
                QualityIssue(
                    severity="info",
                    category="constant",
                    column=str(col),
                    message=f"Column '{col}' has only one unique value.",
                )
            )

    numeric_cols = df.select_dtypes(include="number").columns
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 4:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outlier_count = int(((series < lower) | (series > upper)).sum())
        if outlier_count > 0:
            issues.append(
                QualityIssue(
                    severity="info",
                    category="outliers",
                    column=str(col),
                    message=f"Column '{col}' has {outlier_count} potential outlier(s) (IQR method).",
                    details={"outlier_count": outlier_count},
                )
            )

    return issues
