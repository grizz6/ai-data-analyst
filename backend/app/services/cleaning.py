import pandas as pd

from app.config import settings
from app.models.schemas import CleaningAction


def clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, list[CleaningAction]]:
    cleaned = df.copy()
    actions: list[CleaningAction] = []

    dup_before = len(cleaned)
    cleaned = cleaned.drop_duplicates()
    removed = dup_before - len(cleaned)
    if removed > 0:
        actions.append(
            CleaningAction(
                action="drop_duplicates",
                description=f"Removed {removed} duplicate row(s).",
                rows_affected=removed,
            )
        )

    for col in list(cleaned.columns):
        null_pct = cleaned[col].isna().mean()
        if null_pct >= settings.missing_threshold_drop:
            cleaned = cleaned.drop(columns=[col])
            actions.append(
                CleaningAction(
                    action="drop_column",
                    column=str(col),
                    description=f"Dropped column '{col}' ({null_pct * 100:.1f}% missing).",
                )
            )

    for col in cleaned.columns:
        series = cleaned[col]
        if series.isna().sum() == 0:
            continue

        if pd.api.types.is_numeric_dtype(series):
            fill_value = series.median()
            missing = int(series.isna().sum())
            cleaned[col] = series.fillna(fill_value)
            actions.append(
                CleaningAction(
                    action="impute_median",
                    column=str(col),
                    description=f"Filled {missing} missing value(s) in '{col}' with median ({fill_value:.4g}).",
                    rows_affected=missing,
                )
            )
        else:
            mode = series.mode(dropna=True)
            if len(mode) == 0:
                continue
            fill_value = mode.iloc[0]
            missing = int(series.isna().sum())
            cleaned[col] = series.fillna(fill_value)
            actions.append(
                CleaningAction(
                    action="impute_mode",
                    column=str(col),
                    description=f"Filled {missing} missing value(s) in '{col}' with most common value.",
                    rows_affected=missing,
                )
            )

    for col in cleaned.columns:
        if cleaned[col].dtype != object:
            continue
        name_hints_date = any(token in str(col).lower() for token in ("date", "time", "timestamp"))
        if not name_hints_date:
            continue
        with pd.option_context("mode.chained_assignment", None):
            parsed = pd.to_datetime(cleaned[col], errors="coerce", utc=False)
        if parsed.notna().mean() > 0.8:
                cleaned[col] = parsed
                actions.append(
                    CleaningAction(
                        action="parse_datetime",
                        column=str(col),
                        description=f"Parsed column '{col}' as datetime.",
                    )
                )

    return cleaned, actions
