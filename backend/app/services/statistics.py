"""Further statistical tests: distribution shape, rank correlation, associations
between categories, differences between groups, and how values go missing.

Every test runs on the prepared data (no filled-in values, no identifier
columns) and on bounded numbers of columns, so a wide file stays fast. When
many tests run at once some come out "significant" by chance, so each family's
p-values are also adjusted with the Benjamini-Hochberg procedure.
"""

import itertools
import math

import numpy as np
import pandas as pd
from scipy import stats

from app.models.schemas import (
    CategoricalAssociation,
    DistributionStat,
    GroupDifference,
    MissingPattern,
    RankCorrelation,
    StatisticalTests,
)
from app.services.semantics import is_categorical

MAX_NUMERIC_COLUMNS = 30
MAX_CATEGORICAL_COLUMNS = 15
MAX_GROUPS = 20
MIN_GROUP_SIZE = 3
MIN_NORMALITY_N = 20
KENDALL_MAX_ROWS = 5_000
KENDALL_PAIRS = 10
REPORT_LIMIT = 10
MIN_RANK_CORRELATION = 0.3
MIN_MISSING_CORRELATION = 0.5
ZSCORE_LIMIT = 3.0
SEED = 7


def compute_statistics(df: pd.DataFrame) -> StatisticalTests:
    numeric = _numeric_columns(df)[:MAX_NUMERIC_COLUMNS]
    categorical = _categorical_columns(df)[:MAX_CATEGORICAL_COLUMNS]
    return StatisticalTests(
        distributions=[d for col in numeric if (d := _distribution(df[col].dropna(), col)) is not None],
        rank_correlations=_rank_correlations(df, numeric),
        categorical_associations=_categorical_associations(df, categorical),
        group_differences=_group_differences(df, categorical, numeric),
        missing_patterns=_missing_patterns(df),
    )


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Adjusted p-values (q-values) controlling the false discovery rate."""
    m = len(p_values)
    if m == 0:
        return []
    order = np.argsort(p_values)
    ranked = np.asarray(p_values, dtype=float)[order] * m / np.arange(1, m + 1)
    # Make them non-decreasing from the largest rank down, and cap at 1.
    adjusted = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1.0)
    out = np.empty(m)
    out[order] = adjusted
    return [float(v) for v in out]


def _numeric_columns(df: pd.DataFrame) -> list[str]:
    return [
        str(c)
        for c in df.select_dtypes(include="number").columns
        if not pd.api.types.is_bool_dtype(df[c]) and df[c].nunique() > 1
    ]


def _categorical_columns(df: pd.DataFrame) -> list[str]:
    return [
        str(c)
        for c in df.columns
        if not pd.api.types.is_numeric_dtype(df[c])
        and not pd.api.types.is_datetime64_any_dtype(df[c])
        and is_categorical(df[c])
    ]


def _finite(value: float | np.floating) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


def _shape(skew: float | None, kurt: float | None) -> str:
    if skew is None:
        return "not enough values"
    if skew > 1:
        shape = "strongly right-skewed (a long tail of high values)"
    elif skew > 0.5:
        shape = "right-skewed"
    elif skew < -1:
        shape = "strongly left-skewed (a long tail of low values)"
    elif skew < -0.5:
        shape = "left-skewed"
    else:
        shape = "roughly symmetric"
    if kurt is not None and kurt > 3:
        shape += ", with heavy tails"
    return shape


def _distribution(series: pd.Series, col: str) -> DistributionStat | None:
    values = series.to_numpy(dtype=float)
    if len(values) < 3 or np.ptp(values) == 0:
        return None
    skew = _finite(stats.skew(values, bias=False))
    kurt = _finite(stats.kurtosis(values, bias=False))
    normality_p = _finite(stats.normaltest(values).pvalue) if len(values) >= MIN_NORMALITY_N else None
    z = (values - values.mean()) / values.std(ddof=1)
    return DistributionStat(
        column=col,
        n=len(values),
        skewness=skew,
        kurtosis=kurt,
        normality_p=normality_p,
        shape=_shape(skew, kurt),
        zscore_outliers=int((np.abs(z) > ZSCORE_LIMIT).sum()),
    )


def _rank_correlations(df: pd.DataFrame, numeric: list[str]) -> list[RankCorrelation]:
    if len(numeric) < 2:
        return []
    data = df[numeric].astype(float)
    # Pearson on ranks is Spearman's rho; both use rows where the pair has values.
    spearman = data.rank().corr().to_numpy()
    pearson = data.corr().to_numpy()
    present = data.notna().to_numpy(dtype=int)
    pair_n = present.T @ present

    pairs: list[tuple[str, str, float, float | None, int, float | None]] = []
    for i, j in itertools.combinations(range(len(numeric)), 2):
        rho, n = float(spearman[i, j]), int(pair_n[i, j])
        if math.isnan(rho) or n < 4:
            continue
        pairs.append((numeric[i], numeric[j], rho, _finite(pearson[i, j]), n, _rho_p_value(rho, n)))

    adjusted = benjamini_hochberg([p if p is not None else 1.0 for *_, p in pairs])
    rows = [
        RankCorrelation(
            column_a=a,
            column_b=b,
            n=n,
            pearson=r,
            spearman=round(rho, 4),
            kendall=None,
            p_value=p,
            p_adjusted=q,
        )
        for (a, b, rho, r, n, p), q in zip(pairs, adjusted, strict=True)
        if abs(rho) >= MIN_RANK_CORRELATION
    ]
    rows.sort(key=lambda r: abs(r.spearman), reverse=True)
    rows = rows[:REPORT_LIMIT]

    # Kendall's tau is slower, so it's computed for the strongest pairs on a sample.
    sample = data.sample(n=min(len(data), KENDALL_MAX_ROWS), random_state=SEED)
    for row in rows[:KENDALL_PAIRS]:
        both = sample[[row.column_a, row.column_b]].dropna()
        if len(both) >= 4:
            row.kendall = _finite(stats.kendalltau(both[row.column_a], both[row.column_b]).statistic)
    return rows


def _rho_p_value(rho: float, n: int) -> float | None:
    if n < 4:
        return None
    if abs(rho) >= 1:
        return 0.0
    t = rho * math.sqrt((n - 2) / (1 - rho**2))
    return float(2 * stats.t.sf(abs(t), df=n - 2))


def _categorical_associations(df: pd.DataFrame, categorical: list[str]) -> list[CategoricalAssociation]:
    found: list[CategoricalAssociation] = []
    for a, b in itertools.combinations(categorical, 2):
        table = pd.crosstab(df[a], df[b])
        if table.shape[0] < 2 or table.shape[1] < 2:
            continue
        result = stats.chi2_contingency(table)
        n = int(table.to_numpy().sum())
        smaller = min(table.shape) - 1
        expected = np.asarray(result.expected_freq)
        found.append(
            CategoricalAssociation(
                column_a=a,
                column_b=b,
                n=n,
                chi_square=round(float(result.statistic), 3),
                dof=int(result.dof),
                p_value=float(result.pvalue),
                p_adjusted=None,
                cramers_v=round(math.sqrt(float(result.statistic) / (n * smaller)), 4),
                sparse=bool((expected < 5).mean() > 0.2),
            )
        )
    for row, q in zip(found, benjamini_hochberg([r.p_value for r in found]), strict=True):
        row.p_adjusted = q
    found.sort(key=lambda r: r.cramers_v, reverse=True)
    return found[:REPORT_LIMIT]


def _group_differences(
    df: pd.DataFrame, categorical: list[str], numeric: list[str]
) -> list[GroupDifference]:
    found: list[GroupDifference] = []
    for group_col in categorical:
        levels = df[group_col].dropna().unique()
        if not 2 <= len(levels) <= MAX_GROUPS:
            continue
        for value_col in numeric:
            frame = df[[group_col, value_col]].dropna()
            groups = {
                str(name): g[value_col].to_numpy(dtype=float)
                for name, g in frame.groupby(group_col, observed=True)
                if len(g) >= MIN_GROUP_SIZE
            }
            if len(groups) < 2:
                continue
            arrays = list(groups.values())
            values = np.concatenate(arrays)
            total_ss = float(((values - values.mean()) ** 2).sum())
            if total_ss == 0:
                continue
            between_ss = sum(len(g) * (g.mean() - values.mean()) ** 2 for g in arrays)
            anova = stats.f_oneway(*arrays)
            kruskal = stats.kruskal(*arrays)
            means = {name: float(g.mean()) for name, g in groups.items()}
            high = max(means, key=lambda k: means[k])
            low = min(means, key=lambda k: means[k])
            found.append(
                GroupDifference(
                    group_column=group_col,
                    value_column=value_col,
                    groups=len(groups),
                    n=len(values),
                    anova_f=_finite(anova.statistic),
                    anova_p=_finite(anova.pvalue),
                    kruskal_h=_finite(kruskal.statistic),
                    kruskal_p=_finite(kruskal.pvalue),
                    p_adjusted=None,
                    eta_squared=round(float(between_ss / total_ss), 4),
                    highest_group=high,
                    highest_mean=round(means[high], 4),
                    lowest_group=low,
                    lowest_mean=round(means[low], 4),
                )
            )
    pvals = [r.kruskal_p if r.kruskal_p is not None else 1.0 for r in found]
    for row, q in zip(found, benjamini_hochberg(pvals), strict=True):
        row.p_adjusted = q
    found.sort(key=lambda r: r.eta_squared, reverse=True)
    return found[:REPORT_LIMIT]


def _missing_patterns(df: pd.DataFrame) -> list[MissingPattern]:
    missing = df.isna()
    partly = [c for c in missing.columns if 0 < missing[c].mean() < 1]
    if len(partly) < 2:
        return []
    corr = missing[partly].astype(float).corr().to_numpy()
    found = []
    for i, j in itertools.combinations(range(len(partly)), 2):
        a, b, r = partly[i], partly[j], float(corr[i, j])
        if not math.isnan(r) and r >= MIN_MISSING_CORRELATION:
            found.append(
                MissingPattern(
                    column_a=str(a),
                    column_b=str(b),
                    both_missing=int((missing[a] & missing[b]).sum()),
                    correlation=round(float(r), 4),
                )
            )
    found.sort(key=lambda m: m.correlation, reverse=True)
    return found[:REPORT_LIMIT]


SIGNIFICANT = 0.05


def statistics_insights(tests: StatisticalTests) -> list[tuple[str, str]]:
    """(title, sentence) pairs for the clearest results, at most one per kind of test."""
    from app.services.analysis import format_p

    found: list[tuple[str, str]] = []
    diff = next((d for d in tests.group_differences if (d.p_adjusted or 1) < SIGNIFICANT), None)
    if diff is not None:
        found.append(
            (
                f"{diff.value_column} by {diff.group_column}",
                f"'{diff.value_column}' differs between '{diff.group_column}' groups: highest in "
                f"'{diff.highest_group}' (mean {diff.highest_mean:,.2f}), lowest in '{diff.lowest_group}' "
                f"(mean {diff.lowest_mean:,.2f}). The groups explain {diff.eta_squared:.0%} of its variation "
                f"(Kruskal-Wallis, adjusted {format_p(diff.p_adjusted)}).",
            )
        )
    assoc = next((a for a in tests.categorical_associations if (a.p_adjusted or 1) < SIGNIFICANT), None)
    if assoc is not None:
        strength = "strongly" if assoc.cramers_v >= 0.5 else "moderately" if assoc.cramers_v >= 0.3 else "weakly"
        found.append(
            (
                f"{assoc.column_a} and {assoc.column_b}",
                f"'{assoc.column_a}' and '{assoc.column_b}' are {strength} related (Cramér's V "
                f"{assoc.cramers_v:.2f}, chi-square adjusted {format_p(assoc.p_adjusted)})"
                + (", though some combinations are rare, so treat the p-value with care." if assoc.sparse else "."),
            )
        )
    curved = next(
        (
            r
            for r in tests.rank_correlations
            if r.pearson is not None and abs(r.spearman) - abs(r.pearson) >= 0.1 and (r.p_adjusted or 1) < SIGNIFICANT
        ),
        None,
    )
    if curved is not None:
        found.append(
            (
                f"{curved.column_a} and {curved.column_b} (not a straight line)",
                f"'{curved.column_a}' and '{curved.column_b}' rise and fall together more consistently "
                f"(Spearman {curved.spearman:.2f}) than a straight line shows (Pearson {curved.pearson:.2f}), "
                "so the relationship is curved.",
            )
        )
    skewed = [d.column for d in tests.distributions if d.skewness is not None and abs(d.skewness) > 1]
    if skewed:
        found.append(
            (
                "Skewed columns",
                f"{', '.join(repr(c) for c in skewed[:5])} {'is' if len(skewed) == 1 else 'are'} strongly skewed, "
                "so the median describes a typical value better than the mean.",
            )
        )
    return found
