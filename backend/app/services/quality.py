from collections.abc import Collection

import numpy as np
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


# Beyond this, squaring a value (for a variance) or subtracting two (for a range)
# overflows, so the number can't be analyzed. No real measurement comes close.
MAX_MAGNITUDE = 1e100


def unusable_numbers(df: pd.DataFrame) -> tuple[pd.DataFrame, list[QualityIssue]]:
    """Infinite and astronomically large numbers, blanked so every statistic stays finite.

    Returns a copy with those cells set to missing, and one issue per column saying so.
    """
    issues: list[QualityIssue] = []
    out = df
    for col in df.select_dtypes(include="number").columns:
        values = df[col].astype("float64")
        bad = ~np.isfinite(values) & values.notna() | (values.abs() > MAX_MAGNITUDE)
        count = int(bad.sum())
        if not count:
            continue
        if out is df:
            out = df.copy()
        out[col] = values.mask(bad)
        issues.append(
            QualityIssue(
                severity="warning",
                category="invalid_values",
                column=str(col),
                message=(
                    f"Column '{col}' has {count:,} infinite or impossibly large value{'s' if count != 1 else ''} "
                    f"(beyond ±1e100); {'they are' if count != 1 else 'it is'} treated as missing."
                ),
                details={"count": count},
            )
        )
    return out, issues
