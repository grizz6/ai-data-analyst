from collections.abc import Collection

import pandas as pd

from app.models.schemas import QualityIssue
from app.services import semantics


def check_quality(df: pd.DataFrame, identifiers: Collection[str] = ()) -> list[QualityIssue]:
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

    numeric_cols = [c for c in df.select_dtypes(include="number").columns if c not in identifiers]
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

    for col in df.columns:
        if col in identifiers:
            continue
        issue = _numbers_as_text(df, col) or _inconsistent_labels(df, col)
        if issue:
            issues.append(issue)

    return issues


def _numbers_as_text(df: pd.DataFrame, col) -> QualityIssue | None:
    if semantics.parse_numeric_text(df[col]) is None:
        return None
    example = str(df[col].dropna().iloc[0]).strip()
    return QualityIssue(
        severity="warning",
        category="type",
        column=str(col),
        message=(
            f"Column '{col}' stores numbers as text (e.g. '{example}'), "
            "so it can't be summarized until converted."
        ),
        details={"example": example},
    )


def _inconsistent_labels(df: pd.DataFrame, col) -> QualityIssue | None:
    if not pd.api.types.is_object_dtype(df[col]) or not semantics.is_categorical(df[col]):
        return None
    variants = semantics.label_variants(df[col])
    if not variants:
        return None
    examples = "; ".join(" / ".join(repr(s) for s in spellings) for spellings in list(variants.values())[:2])
    return QualityIssue(
        severity="warning",
        category="labels",
        column=str(col),
        message=(
            f"Column '{col}' writes {len(variants)} label(s) more than one way ({examples}), "
            "which splits one category into several."
        ),
        details={"labels_affected": len(variants)},
    )
