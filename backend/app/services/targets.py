"""Which columns look like outcomes worth explaining or predicting later.

Only used to suggest next steps: nothing is trained here.
"""

from typing import Literal

import pandas as pd

from app.models.schemas import TargetSuggestion
from app.services.semantics import is_categorical, name_words

Task = Literal["classification", "regression"]

MIN_ROWS = 30
MAX_CLASSES = 20

TARGET_WORDS = {
    "target", "label", "class", "outcome", "result", "churn", "churned", "default", "fraud", "survived",
    "status", "y", "price", "sales", "revenue", "amount", "total", "profit", "cost", "score", "rating",
    "salary", "income", "value", "quantity", "demand", "risk", "grade", "approved", "converted", "spend",
    "spending",
}  # fmt: skip


def suggest_targets(df: pd.DataFrame, limit: int = 5) -> list[TargetSuggestion]:
    """Columns worth predicting, likeliest first: outcome-like names, then the last usable column."""
    usable = [str(c) for c in df.columns if target_task(df[c]) is not None]
    scored = []
    for position, col in enumerate(usable):
        words = {w.lower() for w in name_words(col)}
        named = bool(words & TARGET_WORDS)
        last = position == len(usable) - 1
        reason = "name suggests an outcome" if named else "last column" if last else "can be predicted"
        scored.append((not named, not last, position, col, reason))
    scored.sort()
    return [
        TargetSuggestion(column=col, task=target_task(df[col]) or "regression", reason=reason)
        for *_, col, reason in scored[:limit]
    ]


def target_task(series: pd.Series) -> Task | None:
    present = series.dropna()
    if len(present) < MIN_ROWS or present.nunique() < 2 or pd.api.types.is_datetime64_any_dtype(series):
        return None
    if pd.api.types.is_bool_dtype(series):
        return "classification"
    if pd.api.types.is_numeric_dtype(series):
        if pd.api.types.is_integer_dtype(series) and present.nunique() <= 10:
            return "classification"
        return "regression"
    if is_categorical(series) and present.nunique() <= MAX_CLASSES:
        return "classification"
    return None
