"""Cleaning happens in two steps, on purpose.

prepare_dataframe() only removes and retypes: duplicate rows, mostly empty
columns, and date parsing. The statistics are computed on its output, so
every figure reflects values that were actually recorded.

fill_missing() then fills gaps for the cleaned dataset people preview and
export. Filled values never feed a statistic: a median-filled column has an
artificially small spread and a spike at its median.
"""

from collections.abc import Collection

import pandas as pd

from app.config import settings
from app.models.schemas import CleaningAction

DATE_NAME_HINTS = ("date", "time", "timestamp")
# Share of the non-missing values that must parse before a column becomes a date column.
DATE_PARSE_THRESHOLD = 0.8


def clean_dataframe(
    df: pd.DataFrame, identifiers: Collection[str] = ()
) -> tuple[pd.DataFrame, list[CleaningAction]]:
    """Both steps together: the fully cleaned frame and every action taken."""
    prepared, prepare_actions = prepare_dataframe(df)
    filled, fill_actions = fill_missing(prepared, identifiers)
    return filled, prepare_actions + fill_actions


def prepare_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, list[CleaningAction]]:
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

    # Parse dates before anything is filled, so a missing date stays missing.
    for col in cleaned.columns:
        if cleaned[col].dtype != object:
            continue
        if not any(token in str(col).lower() for token in DATE_NAME_HINTS):
            continue
        present = cleaned[col].notna()
        if not present.any():
            continue
        parsed = pd.to_datetime(cleaned[col], errors="coerce")
        if parsed[present].notna().mean() > DATE_PARSE_THRESHOLD:
            cleaned[col] = parsed
            actions.append(
                CleaningAction(
                    action="parse_datetime",
                    column=str(col),
                    description=f"Parsed column '{col}' as datetime.",
                )
            )

    return cleaned, actions


def fill_missing(
    df: pd.DataFrame, identifiers: Collection[str] = ()
) -> tuple[pd.DataFrame, list[CleaningAction]]:
    filled = df.copy()
    actions: list[CleaningAction] = []

    for col in filled.columns:
        series = filled[col]
        missing = int(series.isna().sum())
        # A missing ID or date can't be guessed: a median ID points at the wrong
        # record and a most-common date invents an event.
        if missing == 0 or col in identifiers or pd.api.types.is_datetime64_any_dtype(series):
            continue

        if pd.api.types.is_numeric_dtype(series):
            fill_value = series.median()
            filled[col] = series.fillna(fill_value)
            actions.append(
                CleaningAction(
                    action="impute_median",
                    column=str(col),
                    description=(
                        f"Filled {missing} missing value(s) in '{col}' with the median "
                        f"({fill_value:.4g}) in the cleaned data. Statistics use recorded values only."
                    ),
                    rows_affected=missing,
                )
            )
        else:
            mode = series.mode(dropna=True)
            if len(mode) == 0:
                continue
            filled[col] = series.fillna(mode.iloc[0])
            actions.append(
                CleaningAction(
                    action="impute_mode",
                    column=str(col),
                    description=(
                        f"Filled {missing} missing value(s) in '{col}' with the most common value "
                        "in the cleaned data. Statistics use recorded values only."
                    ),
                    rows_affected=missing,
                )
            )

    return filled, actions
