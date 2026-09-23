"""Cleaning happens in two steps, on purpose.

prepare_dataframe() only removes, retypes and normalizes: duplicate rows, mostly
empty columns, numbers stored as text, labels written several ways, and dates.
The statistics are computed on its output, so every figure reflects values that
were actually recorded.

fill_missing() then fills gaps for the cleaned dataset people preview and
export. Filled values never feed a statistic: a median-filled column has an
artificially small spread and a spike at its median.
"""

from collections.abc import Collection

import pandas as pd

from app.config import settings
from app.models.schemas import CleaningAction
from app.services import semantics

DATE_NAME_HINTS = ("date", "time", "timestamp")
# Share of the non-missing values that must parse before a column becomes a date column.
DATE_PARSE_THRESHOLD = 0.8


def clean_dataframe(
    df: pd.DataFrame, identifiers: Collection[str] = ()
) -> tuple[pd.DataFrame, list[CleaningAction]]:
    """Both steps together: the fully cleaned frame and every action taken."""
    prepared, prepare_actions = prepare_dataframe(df, identifiers)
    filled, fill_actions = fill_missing(prepared, identifiers)
    return filled, prepare_actions + fill_actions


def prepare_dataframe(
    df: pd.DataFrame, identifiers: Collection[str] = ()
) -> tuple[pd.DataFrame, list[CleaningAction]]:
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
        if col in identifiers:
            continue
        action = _convert_numeric_text(cleaned, col) or _unify_labels(cleaned, col)
        if action:
            actions.append(action)

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


def _convert_numeric_text(df: pd.DataFrame, col) -> CleaningAction | None:
    numbers = semantics.parse_numeric_text(df[col])
    if numbers is None:
        return None
    original = df[col]
    had_value = original.notna() & (original.astype(str).str.strip() != "")
    unreadable = int((had_value & numbers.isna()).sum())
    df[col] = numbers

    description = (
        f"Converted '{col}' from text to numbers "
        "(removed currency signs, thousands separators and %)."
    )
    if unreadable:
        description += f" {unreadable} value(s) that weren't numbers became missing."
    return CleaningAction(
        action="convert_numeric_text",
        column=str(col),
        description=description,
        rows_affected=int(numbers.notna().sum()),
    )


def _unify_labels(df: pd.DataFrame, col) -> CleaningAction | None:
    if not pd.api.types.is_object_dtype(df[col]) or not semantics.is_categorical(df[col]):
        return None
    variants = semantics.label_variants(df[col])
    if not variants:
        return None

    mapping = {
        spelling: canonical
        for canonical, spellings in variants.items()
        for spelling in spellings
        if spelling != canonical
    }
    changed = int(df[col].isin(list(mapping)).sum())
    df[col] = df[col].replace(mapping)

    examples = "; ".join(" / ".join(repr(s) for s in spellings) for spellings in list(variants.values())[:2])
    return CleaningAction(
        action="unify_labels",
        column=str(col),
        description=(
            f"Unified {changed} value(s) in '{col}' that differed only in case or spacing "
            f"({examples}), using the most common spelling."
        ),
        rows_affected=changed,
    )
