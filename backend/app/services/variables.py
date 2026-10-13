"""A profile of every column, one at a time: the core of the exploratory pass.

For each column it works out what kind of variable it is (binary, number,
count, category, date, identifier, free text), then the numbers and chart
data that kind needs:

- Numbers: summary statistics, a histogram, a density curve (for the violin
  plot), a Q-Q plot against a normal distribution, the values along the time
  axis, and outliers under two rules (1.5 x IQR and |z| > 3) with the most
  extreme rows, a guess at each one's cause, and the mean, median, spread
  and strongest correlation with and without them.
- Binary columns (0/1, true/false, yes/no, or any two values): the split, and
  every other column ranked by how much it differs between the two groups.
- Categories: counts and shares; dates: rows per period.

Charts are sent as data (bins, curves, quantiles), not drawn figures, so a
100,000-row file costs a few kilobytes per column.
"""

import math

import numpy as np
import pandas as pd
from scipy import stats

from app.models.schemas import (
    BinaryComparison,
    BinaryInfo,
    BinarySplit,
    BoxStats,
    CategoryCount,
    Curve,
    GroupBox,
    Histogram,
    OutlierCorrelation,
    OutlierRow,
    OutlierSummary,
    VariableKind,
    VariableProfile,
)
from app.services.semantics import is_categorical
from app.services.statistics import benjamini_hochberg
from app.services.timeaxis import TimeAxis

SEED = 5
HISTOGRAM_BINS = 30
DENSITY_POINTS = 80
DENSITY_MAX_ROWS = 5_000
QQ_POINTS = 100
TIMELINE_MAX_POINTS = 200
TOP_CATEGORIES = 12
OUTLIER_ROWS = 10
Z_THRESHOLD = 3.0
IQR_REACH = 1.5
# Tukey's "far out" fences: values past them would squash the charts, so they zoom in.
FAR_REACH = 3.0
COUNT_MAX_DISTINCT = 20
# Wide files: columns past this many get statistics but no chart data.
MAX_CHARTED_COLUMNS = 150
MAX_BINARY_COLUMNS = 5
MAX_SPLIT_COLUMNS = 3
MAX_COMPARED_COLUMNS = 100
TOP_COMPARISONS = 15
TEST_MAX_ROWS = 20_000
PARTNER_SAMPLE_ROWS = 5_000
LOPSIDED_SHARE = 10.0

POSITIVE_WORDS = {"1", "1.0", "true", "yes", "y", "t"}
PLACEHOLDER_CODES = {-1.0, -9.0, -99.0, -999.0, -9999.0, 99.0, 999.0, 9999.0, 99999.0}
TYPO_RATIO = 50


def profile_variables(
    prepared: pd.DataFrame, identifiers: list[str], axis: TimeAxis | None
) -> list[VariableProfile]:
    kinds = {str(col): _kind(prepared[col], str(col) in identifiers) for col in prepared.columns}
    label_col = next((c for c in identifiers if c in prepared.columns), None)
    axis_cols = set(axis.columns) if axis else set()

    binaries = [c for c, k in kinds.items() if k == "binary"][:MAX_BINARY_COLUMNS]
    compared = {b: _compare_against(prepared, b, kinds) for b in binaries}
    partners = _partners(prepared, kinds)

    profiles = []
    charted = 0
    for col in prepared.columns:
        name = str(col)
        series = prepared[col]
        kind = kinds[name]
        with_charts = kind not in ("identifier", "constant") and charted < MAX_CHARTED_COLUMNS
        if with_charts:
            charted += 1
        profile = _base(name, series, kind)
        if kind in ("number", "count"):
            _numeric(profile, series, prepared, partners.get(name), label_col, with_charts)
            if with_charts and axis is not None and name not in axis_cols:
                _timeline(profile, series, axis)
            profile.splits = [
                split
                for b in binaries[:MAX_SPLIT_COLUMNS]
                if b != name and (split := _split(prepared, name, b, compared[b])) is not None
            ]
        elif kind == "binary":
            _binary(profile, series)
            profile.compared = compared.get(name, [])
            if with_charts and axis is not None and name not in axis_cols:
                _timeline(profile, _as_positive(series, profile.binary), axis)
        elif kind in ("category", "text"):
            _categories(profile, series)
        elif kind == "date":
            _dates(profile, series)
        if not with_charts and kind not in ("identifier", "constant"):
            profile.flags.append("Charts left out: the file has more columns than the dashboard draws.")
        profiles.append(profile)
    return profiles


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------


def _kind(series: pd.Series, identifier: bool) -> VariableKind:
    if identifier:
        return "identifier"
    values = series.dropna()
    distinct = values.nunique()
    if distinct <= 1:
        return "constant"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "date"
    if distinct == 2:
        return "binary"
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        whole = bool((values % 1 == 0).all())
        return "count" if whole and distinct <= COUNT_MAX_DISTINCT and values.min() >= 0 else "number"
    return "category" if is_categorical(series) else "text"


def _base(name: str, series: pd.Series, kind: VariableKind) -> VariableProfile:
    count = int(series.notna().sum())
    missing = int(series.isna().sum())
    profile = VariableProfile(
        name=name,
        kind=kind,
        count=count,
        missing=missing,
        missing_share=sig(100 * missing / len(series), 2) if len(series) else 0.0,
        distinct=int(series.nunique()),
    )
    if profile.missing_share >= 5:
        profile.flags.append(f"{profile.missing_share:g}% of values are missing.")
    if kind == "constant":
        profile.flags.append(
            "One value plus blanks: the blanks may mean 'no' (a yes/no flag), so check before treating them as missing."
            if missing and profile.distinct == 1
            else "Only one value: it can't explain or predict anything."
        )
    if kind == "identifier":
        unique = profile.distinct == count
        profile.flags.append(
            "Identifier: kept out of statistics." + (" Unique on every row." if unique else " Some values repeat.")
        )
    return profile


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def _numeric(
    profile: VariableProfile,
    series: pd.Series,
    df: pd.DataFrame,
    partner: str | None,
    label_col: str | None,
    with_charts: bool,
) -> None:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    values = values[np.isfinite(values)]
    if values.empty:
        return
    mean, std = float(values.mean()), float(values.std(ddof=1)) if len(values) > 1 else 0.0
    skew = float(values.skew()) if len(values) > 2 else None  # type: ignore[arg-type]
    profile.mean, profile.median, profile.std = sig(mean), sig(float(values.median())), sig(std)
    profile.min, profile.max = sig(float(values.min())), sig(float(values.max()))
    profile.skewness = sig(skew, 3) if skew is not None and math.isfinite(skew) else None
    profile.box = box_stats(values)

    if profile.skewness is not None and abs(profile.skewness) >= 1:
        side = "right" if profile.skewness > 0 else "left"
        profile.flags.append(
            f"Strongly {side}-skewed (skewness {profile.skewness:g}): the median is the better typical value."
        )
    zeros = 100 * float((values == 0).mean())
    if zeros >= 30:
        profile.flags.append(f"{zeros:.0f}% of values are zero.")
    top_share = 100 * float(values.value_counts(normalize=True).iloc[0])
    if top_share >= 95:
        profile.flags.append(f"Almost constant: one value covers {top_share:.0f}% of rows.")

    profile.outliers = _outliers(values, df, profile.name, partner, label_col)
    if profile.outliers and profile.outliers.iqr_share >= 5:
        profile.flags.append(f"{profile.outliers.iqr_share:g}% of values are outliers by the IQR rule.")

    if not with_charts:
        return
    shown = _zoom(profile, values)
    profile.histogram = _histogram(shown, profile.kind == "count")
    profile.density = _density(shown)
    profile.qq = _qq(values)


def _zoom(profile: VariableProfile, values: pd.Series) -> pd.Series:
    """Values to chart: all of them, unless a few far-out ones would squash the rest into one bar."""
    q1, q3 = (float(v) for v in values.quantile([0.25, 0.75]))
    reach = FAR_REACH * (q3 - q1)
    inside = values[(values >= q1 - reach) & (values <= q3 + reach)]
    if reach == 0 or len(inside) == len(values) or len(inside) < 8:
        return values
    profile.view = [sig(float(inside.min())), sig(float(inside.max()))]
    profile.beyond_view = len(values) - len(inside)
    return inside


def box_stats(values: pd.Series) -> BoxStats:
    q1, median, q3 = (float(v) for v in values.quantile([0.25, 0.5, 0.75]))
    reach = IQR_REACH * (q3 - q1)
    inside = values[(values >= q1 - reach) & (values <= q3 + reach)]
    return BoxStats(
        n=len(values),
        q1=sig(q1),
        median=sig(median),
        q3=sig(q3),
        low=sig(float(inside.min() if len(inside) else values.min())),
        high=sig(float(inside.max() if len(inside) else values.max())),
        mean=sig(float(values.mean())),
    )


def _histogram(values: pd.Series, discrete: bool) -> Histogram:
    if discrete:
        low, high = float(values.min()), float(values.max())
        bins: np.ndarray = np.arange(low - 0.5, high + 1.5, 1.0)
    else:
        bins = np.histogram_bin_edges(values, bins=HISTOGRAM_BINS)
    counts, edges = np.histogram(values, bins=bins)
    return Histogram(edges=[sig(float(e)) for e in edges], counts=[int(c) for c in counts])


def _density(values: pd.Series) -> Curve | None:
    if values.nunique() <= 10:
        return None
    sample = values.sample(n=min(len(values), DENSITY_MAX_ROWS), random_state=SEED).to_numpy()
    try:
        kde = stats.gaussian_kde(sample)
    except (np.linalg.LinAlgError, ValueError):
        return None
    grid = np.linspace(values.min(), values.max(), DENSITY_POINTS)
    density = kde(grid)
    return Curve(x=[sig(float(x)) for x in grid], y=[sig(float(y)) for y in density])


def _qq(values: pd.Series) -> Curve | None:
    if len(values) < 8:
        return None
    points = min(QQ_POINTS, len(values))
    probs = (np.arange(1, points + 1) - 0.5) / points
    theoretical = stats.norm.ppf(probs)
    sample = values.quantile(probs).to_numpy()
    return Curve(x=[sig(float(t), 4) for t in theoretical], y=[sig(float(s)) for s in sample])


def _outliers(
    values: pd.Series, df: pd.DataFrame, name: str, partner: str | None, label_col: str | None
) -> OutlierSummary | None:
    if len(values) < 8 or values.nunique() <= 2:
        return None
    q1, median, q3 = (float(v) for v in values.quantile([0.25, 0.5, 0.75]))
    low, high = q1 - IQR_REACH * (q3 - q1), q3 + IQR_REACH * (q3 - q1)
    mean, std = float(values.mean()), float(values.std(ddof=1))
    z = (values - mean) / std if std > 0 else pd.Series(0.0, index=values.index)
    iqr_mask = (values < low) | (values > high)
    z_mask = z.abs() > Z_THRESHOLD
    kept = values[~iqr_mask]
    n = len(values)

    flagged = values[iqr_mask | z_mask]
    non_negative = float((values >= 0).mean()) >= 0.99
    skew = float(values.skew()) if n > 2 else 0.0  # type: ignore[arg-type]
    causes = {idx: _cause(float(v), median, non_negative, skew) for idx, v in flagged.items()}
    # Likely entry errors first, however small, then the furthest from the median.
    order = sorted(
        flagged.index,
        key=lambda i: (causes[i] in (TAIL_CAUSE, PLAUSIBLE_CAUSE), -abs(float(flagged[i]) - median)),
    )[:OUTLIER_ROWS]
    rows = []
    for idx in order:
        value = float(values[idx])
        rules = [rule for rule, mask in (("IQR", iqr_mask), ("z", z_mask)) if bool(mask[idx])]
        label = df.at[idx, label_col] if label_col is not None else None
        rows.append(
            OutlierRow(
                row=int(idx) + 1 if isinstance(idx, (int, np.integer)) else 0,
                value=sig(value),
                z=sig(float(z[idx]), 2),
                rules=rules,
                cause=causes[idx],
                label=None if label is None or pd.isna(label) else str(label),
            )
        )

    return OutlierSummary(
        iqr_low=sig(low),
        iqr_high=sig(high),
        iqr_count=int(iqr_mask.sum()),
        iqr_share=sig(100 * float(iqr_mask.mean()), 2),
        z_threshold=Z_THRESHOLD,
        z_count=int(z_mask.sum()),
        z_share=sig(100 * float(z_mask.mean()), 2),
        mean_all=sig(mean),
        mean_without=sig(float(kept.mean())) if len(kept) else sig(mean),
        median_all=sig(median),
        median_without=sig(float(kept.median())) if len(kept) else sig(median),
        std_all=sig(std),
        std_without=sig(float(kept.std(ddof=1))) if len(kept) > 1 else sig(std),
        correlation=_correlation_shift(df, name, partner, values.index[iqr_mask.to_numpy()]),
        rows=rows,
    )


PLACEHOLDER_CAUSE = "Looks like a placeholder code for a missing value."
NEGATIVE_CAUSE = "Negative in a column that is otherwise never negative: likely an entry error."
TAIL_CAUSE = "Part of the column's long tail: likely a genuine extreme."
PLAUSIBLE_CAUSE = "Rare but plausible value."


def _cause(value: float, median: float, non_negative: bool, skew: float) -> str:
    if value in PLACEHOLDER_CODES:
        return PLACEHOLDER_CAUSE
    if non_negative and value < 0:
        return NEGATIVE_CAUSE
    if median != 0 and abs(value / median) >= TYPO_RATIO:
        ratio = abs(value / median)
        power = round(math.log10(ratio))
        if power >= 2 and abs(ratio / 10**power - 1) <= 0.1:
            return f"About {10**power:,}x the median: possibly a unit mix-up or an extra zeros typo."
        return f"About {ratio:,.0f}x the median: check whether it was entered correctly."
    return TAIL_CAUSE if abs(skew) >= 1 else PLAUSIBLE_CAUSE


def _partners(df: pd.DataFrame, kinds: dict[str, VariableKind]) -> dict[str, str]:
    """Each numeric column's most correlated other numeric column, picked on a sample of rows."""
    numeric = [c for c, k in kinds.items() if k in ("number", "count")]
    if len(numeric) < 2:
        return {}
    sample = df[numeric]
    if len(sample) > PARTNER_SAMPLE_ROWS:
        sample = sample.sample(n=PARTNER_SAMPLE_ROWS, random_state=SEED)
    corr = sample.apply(pd.to_numeric, errors="coerce").astype(float).corr(min_periods=10).abs()
    np.fill_diagonal(corr.values, np.nan)
    return {str(col): str(corr[col].idxmax()) for col in corr.columns if corr[col].notna().any()}


def _correlation_shift(
    df: pd.DataFrame, name: str, other: str | None, outlier_index: pd.Index
) -> OutlierCorrelation | None:
    if other is None:
        return None
    target = pd.to_numeric(df[name], errors="coerce")
    partner = pd.to_numeric(df[other], errors="coerce")
    r_all = target.corr(partner)
    keep = ~df.index.isin(outlier_index)
    r_without = target[keep].corr(partner[keep])
    if pd.isna(r_all) or pd.isna(r_without):
        return None
    return OutlierCorrelation(column=other, r_all=sig(float(r_all), 3), r_without=sig(float(r_without), 3))


def _timeline(profile: VariableProfile, series: pd.Series, axis: TimeAxis) -> None:
    frame = pd.DataFrame({"t": axis.values, "v": pd.to_numeric(series, errors="coerce")}).dropna()
    if frame["t"].nunique() < 3:
        return
    if axis.is_calendar:
        span = (frame["t"].max() - frame["t"].min()).days
        freq, label = _period(span)
        grouped = frame.groupby(frame["t"].dt.to_period(freq).dt.start_time)["v"].mean()
        x = [t.strftime("%Y-%m-%d") for t in grouped.index]
        profile.timeline_label = f"average per {label} along {axis.label}"
    else:
        steps = frame["t"].astype(float)
        if steps.nunique() > TIMELINE_MAX_POINTS:
            bins = pd.cut(steps, TIMELINE_MAX_POINTS)
            grouped = frame.groupby(bins, observed=True)["v"].mean()
            x = [sig(float(b.mid)) for b in grouped.index]
            profile.timeline_label = f"average per bucket along {axis.label}"
        else:
            grouped = frame.groupby(steps)["v"].mean()
            x = [sig(float(s)) for s in grouped.index]
            profile.timeline_label = f"along {axis.label}"
    if len(grouped) > TIMELINE_MAX_POINTS:
        grouped, x = grouped.iloc[-TIMELINE_MAX_POINTS:], x[-TIMELINE_MAX_POINTS:]
        profile.timeline_label += f" (last {TIMELINE_MAX_POINTS} periods)"
    profile.timeline = Curve(x=x, y=[sig(float(v)) for v in grouped.to_numpy()])


# ---------------------------------------------------------------------------
# Binary columns
# ---------------------------------------------------------------------------


def _binary(profile: VariableProfile, series: pd.Series) -> None:
    counts = series.dropna().astype(str).value_counts()
    values = sorted(counts.index, key=str)
    positive = next((v for v in values if v.strip().lower() in POSITIVE_WORDS), None)
    if positive is None:
        # No obvious "yes": call the rarer value the one being counted.
        positive = str(counts.index[-1])
    total = int(counts.sum())
    share = sig(100 * int(counts[positive]) / total, 2)
    profile.binary = BinaryInfo(
        values=values, counts=[int(counts[v]) for v in values], positive=positive, positive_share=share
    )
    minority = min(share, 100 - share)
    if minority < LOPSIDED_SHARE:
        profile.flags.append(
            f"Lopsided: the smaller group is {minority:g}% of rows. Accuracy alone would mislead; "
            "look at precision, recall and AUC."
        )


def _as_positive(series: pd.Series, info: BinaryInfo | None) -> pd.Series:
    """1 where the row has the binary column's counted value, so a timeline shows its rate."""
    if info is None:
        return series
    text = series.astype(str)
    return (text == info.positive).astype(float).where(series.notna())


def _groups(df: pd.DataFrame, binary: str) -> tuple[str, str, pd.Series] | None:
    text = df[binary].astype(str).where(df[binary].notna())
    values = sorted(text.dropna().unique(), key=str)
    if len(values) != 2:
        return None
    positive = next((v for v in values if v.strip().lower() in POSITIVE_WORDS), None)
    if positive is None:
        positive = str(text.value_counts().index[-1])
    negative = next(v for v in values if v != positive)
    return positive, negative, text


def _compare_against(df: pd.DataFrame, binary: str, kinds: dict[str, VariableKind]) -> list[BinaryComparison]:
    groups = _groups(df, binary)
    if groups is None:
        return []
    positive, negative, text = groups
    frame = df if len(df) <= TEST_MAX_ROWS else df.sample(n=TEST_MAX_ROWS, random_state=SEED)
    text = text.loc[frame.index]
    results: list[BinaryComparison] = []
    candidates = [c for c, k in kinds.items() if c != binary and k in ("number", "count", "category", "binary")]
    for col in candidates[:MAX_COMPARED_COLUMNS]:
        if kinds[col] in ("number", "count"):
            values = pd.to_numeric(frame[col], errors="coerce")
            a, b = values[text == positive].dropna(), values[text == negative].dropna()
            if len(a) < 3 or len(b) < 3:
                continue
            try:
                u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
            except ValueError:
                continue
            # Rank-biserial correlation, -1 to 1: positive when the counted group tends higher.
            effect = 2 * float(u) / (len(a) * len(b)) - 1
            results.append(
                BinaryComparison(
                    column=col,
                    kind="numeric",
                    effect=sig(effect, 3),
                    effect_name="rank-biserial",
                    p_value=float(p),
                    detail=(
                        f"median {fmt_number(float(a.median()))} when {binary} = {positive} "
                        f"vs {fmt_number(float(b.median()))} when {negative}"
                    ),
                )
            )
        else:
            cats = frame[col].astype(str).where(frame[col].notna())
            top = cats.value_counts().index[:TOP_CATEGORIES]
            mask = cats.isin(top) & text.notna()
            table = pd.crosstab(cats[mask], text[mask])
            if table.shape[0] < 2 or table.shape[1] < 2:
                continue
            chi2, p, _, _ = stats.chi2_contingency(table)
            n = int(table.to_numpy().sum())
            v = math.sqrt(chi2 / (n * (min(table.shape) - 1))) if n else 0.0
            rates = table[positive] / table.sum(axis=1) * 100 if positive in table.columns else None
            overall = 100 * float((text[mask] == positive).mean())
            detail = ""
            if rates is not None:
                best = rates.idxmax()
                detail = f"{binary} = {positive} in {rates[best]:.0f}% of '{best}' rows vs {overall:.0f}% overall"
            results.append(
                BinaryComparison(
                    column=col,
                    kind="category",
                    effect=sig(v, 3),
                    effect_name="Cramér's V",
                    p_value=float(p),
                    detail=detail,
                )
            )
    adjusted = benjamini_hochberg([r.p_value if r.p_value is not None else 1.0 for r in results])
    for result, p_adj in zip(results, adjusted, strict=True):
        result.p_value = sig(p_adj)
    results.sort(key=lambda r: abs(r.effect), reverse=True)
    return results[:TOP_COMPARISONS]


def _split(df: pd.DataFrame, col: str, binary: str, comparisons: list[BinaryComparison]) -> BinarySplit | None:
    groups = _groups(df, binary)
    if groups is None:
        return None
    positive, negative, text = groups
    values = pd.to_numeric(df[col], errors="coerce")
    boxes = []
    for label in (positive, negative):
        part = values[text == label].dropna()
        if len(part) < 3:
            return None
        boxes.append(GroupBox(label=f"{binary} = {label}", box=box_stats(part.astype(float))))
    match = next((c for c in comparisons if c.column == col), None)
    return BinarySplit(
        binary_column=binary,
        groups=boxes,
        p_value=match.p_value if match else None,
        effect=match.effect if match else None,
    )


# ---------------------------------------------------------------------------
# Categories and dates
# ---------------------------------------------------------------------------


def _categories(profile: VariableProfile, series: pd.Series) -> None:
    counts = series.dropna().astype(str).value_counts()
    total = int(counts.sum())
    if not total:
        return
    top = counts.iloc[:TOP_CATEGORIES]
    profile.categories = [
        CategoryCount(value=str(v), count=int(c), share=sig(100 * int(c) / total, 2)) for v, c in top.items()
    ]
    rest = total - int(top.sum())
    if rest:
        profile.categories.append(
            CategoryCount(
                value=f"{len(counts) - len(top)} others", count=rest, share=sig(100 * rest / total, 2)
            )
        )
    if profile.kind == "category":
        rare = int((counts / total < 0.01).sum())
        if rare:
            profile.flags.append(f"{rare} categories each cover under 1% of rows; consider grouping them.")
        if counts.iloc[0] / total >= 0.9:
            profile.flags.append(f"'{counts.index[0]}' covers {100 * counts.iloc[0] / total:.0f}% of rows.")
    if profile.kind == "text":
        profile.flags.append("Free text: mostly unique values, so it isn't charted as a category.")


def _dates(profile: VariableProfile, series: pd.Series) -> None:
    stamps = series.dropna()
    if stamps.empty:
        return
    first, last = stamps.min(), stamps.max()
    span = (last - first).days
    profile.flags.append(f"From {first:%Y-%m-%d} to {last:%Y-%m-%d} ({span:,} days).")
    freq, label = _period(span)
    counts = stamps.dt.to_period(freq).dt.start_time.value_counts().sort_index()
    if len(counts) > TIMELINE_MAX_POINTS:
        counts = counts.iloc[-TIMELINE_MAX_POINTS:]
    profile.timeline = Curve(x=[t.strftime("%Y-%m-%d") for t in counts.index], y=[float(c) for c in counts.to_numpy()])
    profile.timeline_label = f"rows per {label}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _period(span_days: int) -> tuple[str, str]:
    if span_days <= 120:
        return "D", "day"
    if span_days <= 1_000:
        return "W", "week"
    return ("M", "month") if span_days <= 7_300 else ("Y", "year")


def sig(value: float, digits: int = 6) -> float:
    """Six significant figures: exact enough to read, small enough to send."""
    if value == 0 or not math.isfinite(value):
        return 0.0 if not math.isfinite(value) else value
    if digits < 6:
        return round(value, digits)
    return float(f"{value:.6g}")


def fmt_number(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{value:,.0f}"
