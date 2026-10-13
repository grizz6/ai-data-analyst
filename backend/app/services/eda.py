"""Exploration beyond single columns: duplicates, why values are missing,
numbers within each category, categories against each other, and a data
dictionary to download.

- Duplicates: exact copies of a row, with their row numbers.
- Missing values: for each column with gaps, the other columns that differ
  between rows where it's missing and rows where it isn't. Gaps that depend on
  other columns aren't random, and dropping those rows would bias the rest.
- Breakdowns: every numeric column within every category column's groups
  (box statistics per group, eta squared, Kruskal-Wallis).
- Crosstabs: counts for every pair of category columns (chi-square, Cramer's V).

p-values are Benjamini-Hochberg adjusted within each family.
"""

import csv
import io
import itertools
import math

import pandas as pd
from scipy import stats

from app.models.schemas import (
    AnalysisResult,
    BinaryComparison,
    CategoryBreakdown,
    CategoryCrosstab,
    DuplicateGroup,
    Duplicates,
    GroupBox,
    MissingDependency,
    VariableKind,
)
from app.services.statistics import benjamini_hochberg
from app.services.variables import box_stats, fmt_number, sig

SEED = 7
TEST_MAX_ROWS = 20_000
DUPLICATE_GROUPS = 5
DUPLICATE_ROWS_SHOWN = 10
DUPLICATE_COLUMNS_SHOWN = 8
MISSING_MIN_SHARE = 1.0
MISSING_MAX_SHARE = 95.0
MISSING_COLUMNS = 10
MISSING_COMPARED = 50
MISSING_RELATED = 3
MAX_GROUP_COLUMNS = 8
MAX_GROUP_LEVELS = 30
MAX_VALUE_COLUMNS = 12
GROUPS_SHOWN = 12
CROSSTAB_LEVELS = 10
MIN_GROUP_ROWS = 3
SIGNIFICANT = 0.05

NUMERIC_KINDS = ("number", "count")
GROUP_KINDS = ("category", "binary")


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def duplicates(raw: pd.DataFrame) -> Duplicates:
    if raw.empty:
        return Duplicates(count=0, share=0.0)
    hashes = pd.util.hash_pandas_object(raw, index=False)
    extra = int(hashes.duplicated().sum())
    groups = []
    if extra:
        repeated = hashes[hashes.duplicated(keep=False)]
        for _, members in itertools.islice(repeated.groupby(repeated, sort=False), DUPLICATE_GROUPS):
            first = members.index[0]
            values = raw.loc[first].iloc[:DUPLICATE_COLUMNS_SHOWN]
            groups.append(
                DuplicateGroup(
                    rows=[_row_number(i) for i in members.index[:DUPLICATE_ROWS_SHOWN]],
                    values={str(k): (None if pd.isna(v) else str(v)) for k, v in values.items()},
                )
            )
    return Duplicates(count=extra, share=sig(100 * extra / len(raw)), groups=groups)


def _row_number(index) -> int:
    return int(index) + 1 if isinstance(index, int) or hasattr(index, "__index__") else 0


# ---------------------------------------------------------------------------
# Why values are missing
# ---------------------------------------------------------------------------


def missing_dependencies(df: pd.DataFrame, kinds: dict[str, VariableKind]) -> list[MissingDependency]:
    frame = df if len(df) <= TEST_MAX_ROWS else df.sample(n=TEST_MAX_ROWS, random_state=SEED)
    shares = {c: 100 * float(df[c].isna().mean()) for c in kinds if c in df.columns}
    gappy = sorted(
        (c for c, share in shares.items() if MISSING_MIN_SHARE <= share <= MISSING_MAX_SHARE),
        key=lambda c: -shares[c],
    )[:MISSING_COLUMNS]
    found = []
    for col in gappy:
        missing = frame[col].isna()
        related: list[BinaryComparison] = []
        others = [c for c, k in kinds.items() if c != col and k in (*NUMERIC_KINDS, *GROUP_KINDS)]
        for other in others[:MISSING_COMPARED]:
            comparison = (
                _numeric_by_missing(frame[other], missing, col, other)
                if kinds[other] in NUMERIC_KINDS
                else _category_by_missing(frame[other], missing, col, other)
            )
            if comparison is not None:
                related.append(comparison)
        _adjust(related)
        related = [r for r in related if r.p_value is not None and r.p_value < SIGNIFICANT]
        related.sort(key=lambda r: abs(r.effect), reverse=True)
        found.append(
            MissingDependency(
                column=col,
                missing=int(df[col].isna().sum()),
                missing_share=sig(shares[col]),
                related=related[:MISSING_RELATED],
            )
        )
    return found


def _numeric_by_missing(values: pd.Series, missing: pd.Series, col: str, other: str) -> BinaryComparison | None:
    numbers = pd.to_numeric(values, errors="coerce")
    a, b = numbers[missing].dropna(), numbers[~missing].dropna()
    if len(a) < MIN_GROUP_ROWS or len(b) < MIN_GROUP_ROWS:
        return None
    try:
        u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    except ValueError:
        return None
    return BinaryComparison(
        column=other,
        kind="numeric",
        effect=sig(2 * float(u) / (len(a) * len(b)) - 1, 3),
        effect_name="rank-biserial",
        p_value=float(p),
        detail=(
            f"median {other} is {fmt_number(float(a.median()))} where {col} is missing "
            f"vs {fmt_number(float(b.median()))} where it isn't"
        ),
    )


def _category_by_missing(values: pd.Series, missing: pd.Series, col: str, other: str) -> BinaryComparison | None:
    labels = values.astype(str).where(values.notna())
    top = labels.value_counts().index[:GROUPS_SHOWN]
    keep = labels.isin(top)
    table = pd.crosstab(labels[keep], missing[keep])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return None
    chi2, p, _, _ = stats.chi2_contingency(table)
    n = int(table.to_numpy().sum())
    rates = table[True] / table.sum(axis=1) * 100
    worst = str(rates.idxmax())
    overall = 100 * float(missing[keep].mean())
    return BinaryComparison(
        column=other,
        kind="category",
        effect=sig(math.sqrt(chi2 / (n * (min(table.shape) - 1))) if n else 0.0, 3),
        effect_name="Cramér's V",
        p_value=float(p),
        detail=f"{col} is missing in {rates[worst]:.0f}% of '{worst}' rows vs {overall:.0f}% overall",
    )


# ---------------------------------------------------------------------------
# Numbers within categories, and categories against each other
# ---------------------------------------------------------------------------


def _group_columns(df: pd.DataFrame, kinds: dict[str, VariableKind]) -> list[str]:
    return [c for c, k in kinds.items() if k in GROUP_KINDS and df[c].nunique() <= MAX_GROUP_LEVELS][:MAX_GROUP_COLUMNS]


def breakdowns(df: pd.DataFrame, kinds: dict[str, VariableKind]) -> list[CategoryBreakdown]:
    groups = _group_columns(df, kinds)
    values = [c for c, k in kinds.items() if k in NUMERIC_KINDS][:MAX_VALUE_COLUMNS]
    found = []
    for category, value in itertools.product(groups, values):
        frame = df[[category, value]].dropna()
        labels = frame[category].astype(str)
        numbers = pd.to_numeric(frame[value], errors="coerce").astype(float)
        sizes = labels.value_counts()
        shown = [g for g in sizes.index[:GROUPS_SHOWN] if sizes[g] >= MIN_GROUP_ROWS]
        if len(shown) < 2:
            continue
        parts = [numbers[labels == g] for g in shown]
        # Eta squared: the share of the variation the groups account for.
        everything = pd.concat(parts)
        total = float(((everything - everything.mean()) ** 2).sum())
        between = sum(len(p) * (float(p.mean()) - float(everything.mean())) ** 2 for p in parts)
        try:
            _, p_value = stats.kruskal(*[p.sample(n=min(len(p), TEST_MAX_ROWS), random_state=SEED) for p in parts])
            p = float(p_value) if math.isfinite(p_value) else None
        except ValueError:
            p = None
        # Highest median first, so the chart reads as a ranking.
        order = sorted(range(len(shown)), key=lambda i: -float(parts[i].median()))
        found.append(
            CategoryBreakdown(
                category=category,
                value=value,
                groups=[GroupBox(label=str(shown[i]), box=box_stats(parts[i])) for i in order],
                eta_squared=sig(between / total, 4) if total > 0 else 0.0,
                p_value=p,
            )
        )
    _adjust(found)
    return found


def crosstabs(df: pd.DataFrame, kinds: dict[str, VariableKind]) -> list[CategoryCrosstab]:
    groups = _group_columns(df, kinds)
    found = []
    for row, column in itertools.combinations(groups, 2):
        frame = df[[row, column]].dropna().astype(str)
        top_rows = frame[row].value_counts().index[:CROSSTAB_LEVELS]
        top_cols = frame[column].value_counts().index[:CROSSTAB_LEVELS]
        frame = frame[frame[row].isin(top_rows) & frame[column].isin(top_cols)]
        table = pd.crosstab(frame[row], frame[column]).reindex(index=top_rows, columns=top_cols, fill_value=0)
        if table.shape[0] < 2 or table.shape[1] < 2 or table.to_numpy().sum() == 0:
            continue
        try:
            chi2, p, _, _ = stats.chi2_contingency(table)
        except ValueError:
            continue
        n = int(table.to_numpy().sum())
        found.append(
            CategoryCrosstab(
                row=row,
                column=column,
                row_labels=[str(v) for v in table.index],
                column_labels=[str(v) for v in table.columns],
                counts=[[int(x) for x in r] for r in table.to_numpy()],
                cramers_v=sig(math.sqrt(chi2 / (n * (min(table.shape) - 1))), 4),
                p_value=float(p),
            )
        )
    _adjust(found)
    found.sort(key=lambda c: c.cramers_v, reverse=True)
    return found


def _adjust(items: list) -> None:
    """Benjamini-Hochberg adjust the p_value of each item in place."""
    if not items:
        return
    adjusted = benjamini_hochberg([i.p_value if i.p_value is not None else 1.0 for i in items])
    for item, p in zip(items, adjusted, strict=True):
        if item.p_value is not None:
            item.p_value = sig(p)


# ---------------------------------------------------------------------------
# Data dictionary
# ---------------------------------------------------------------------------

DICTIONARY_FIELDS = [
    "column",
    "type",
    "values",
    "missing",
    "missing_percent",
    "distinct",
    "min",
    "max",
    "mean",
    "median",
    "std_dev",
    "most_common",
    "outliers_iqr",
    "notes",
]


def data_dictionary_csv(result: AnalysisResult) -> bytes:
    """One row per column: its type, completeness, range and anything worth knowing."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=DICTIONARY_FIELDS)
    writer.writeheader()
    for v in result.variables:
        most_common = ""
        if v.binary:
            most_common = f"{v.binary.positive} ({v.binary.positive_share:g}%)"
        elif v.categories:
            most_common = f"{v.categories[0].value} ({v.categories[0].share:g}%)"
        writer.writerow(
            {
                "column": _safe(v.name),
                "type": v.kind,
                "values": v.count,
                "missing": v.missing,
                "missing_percent": v.missing_share,
                "distinct": v.distinct,
                "min": "" if v.min is None else v.min,
                "max": "" if v.max is None else v.max,
                "mean": "" if v.mean is None else v.mean,
                "median": "" if v.median is None else v.median,
                "std_dev": "" if v.std is None else v.std,
                "most_common": _safe(most_common),
                "outliers_iqr": "" if v.outliers is None else v.outliers.iqr_count,
                "notes": _safe(" ".join(v.flags)),
            }
        )
    # utf-8-sig so Excel reads accented column names correctly.
    return out.getvalue().encode("utf-8-sig")


def _safe(text: str) -> str:
    """Stop a spreadsheet from running a cell that starts like a formula."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
