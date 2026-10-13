"""A critical read of the data, the way a senior analyst would brief a colleague.

The exploration says what the data contains; this says what it can and can't
bear. Every point is computed from the results and names its evidence:

- concerns, most serious first: gaps that aren't random, entry errors, columns
  that leak the outcome or duplicate each other, links that only exist because
  of outliers, imbalance, sparse columns, too few rows;
- strengths worth building on;
- conclusions the data can't support (cause and effect, trends without a time
  axis, precise rates from a handful of rows, chance findings among many tests);
- for each suggested analysis, how ready the data is for it and what could
  make its answer wrong.
"""

from dataclasses import dataclass
from typing import Literal

from app.models.schemas import AnalysisResult, AnalystReview, Recommendation, VariableProfile

SIGNIFICANT = 0.05
LEAKAGE_EFFECT = 0.9
NEAR_COPY_R = 0.98
COLLINEAR_R = 0.8
OUTLIER_SHIFT_R = 0.1
# A correlation that moves this much with a few rows removed can't be quoted at all.
MAJOR_SHIFT_R = 0.3
NONLINEAR_GAP = 0.15
SPARSE_SHARE = 30.0
SMALL_SAMPLE = 100
LARGE_SAMPLE = 1_000
EVENTS_PER_PREDICTOR = 10
ROWS_PER_PREDICTOR = 20
MIN_GROUP_ROWS = 30
UNEVEN_GROUPS = 10
SHORT_SERIES = 24
HEAVY_SKEW = 2.0
LOPSIDED = 10.0
MAX_POINTS = 6
ERROR_CAUSE_WORDS = ("placeholder", "entry error", "typo", "entered correctly", "unit mix-up")
PREDICTOR_KINDS = ("number", "count", "category", "binary")


@dataclass
class Concern:
    severity: int  # 3 blocks trustworthy analysis, 2 distorts it, 1 is worth knowing
    short: str
    text: str


# ---------------------------------------------------------------------------
# Shared findings
# ---------------------------------------------------------------------------


def suspicious_values(v: VariableProfile) -> list:
    return [r for r in (v.outliers.rows if v.outliers else []) if any(w in r.cause for w in ERROR_CAUSE_WORDS)]


def leaks(result: AnalysisResult) -> list[tuple[str, str, str]]:
    """(outcome, column, detail) where one column almost perfectly separates a yes/no column."""
    found = []
    for v in result.variables:
        for c in v.compared if v.binary else []:
            if abs(c.effect) >= LEAKAGE_EFFECT and c.p_value is not None and c.p_value < SIGNIFICANT:
                found.append((v.name, c.column, c.detail))
    return found


def outlier_driven(result: AnalysisResult) -> list[tuple[str, str, float, float]]:
    """(column, partner, r with outliers, r without) where the outliers move the correlation a lot."""
    found = []
    for v in result.variables:
        c = v.outliers.correlation if v.outliers else None
        if c and v.outliers and v.outliers.iqr_count and abs(c.r_all - c.r_without) >= OUTLIER_SHIFT_R:
            found.append((v.name, c.column, c.r_all, c.r_without))
    return found


def predictors(result: AnalysisResult, target: str) -> int:
    return sum(1 for v in result.variables if v.name != target and v.kind in PREDICTOR_KINDS)


def _pct(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") + "%"


# ---------------------------------------------------------------------------
# The dataset as a whole
# ---------------------------------------------------------------------------


def review(result: AnalysisResult) -> AnalystReview:
    concerns = _concerns(result)
    concerns.sort(key=lambda c: -c.severity)
    blocking = [c for c in concerns if c.severity == 3]
    distorting = [c for c in concerns if c.severity == 2]
    readiness: Literal["ready", "needs_work", "not_ready"]
    if result.row_count < 30 or len(blocking) >= 2:
        readiness = "not_ready"
        verdict = "Not ready to analyse: " + "; ".join(c.short for c in (blocking or concerns)[:3]) + "."
    elif blocking or distorting:
        fixes = blocking + distorting
        verdict = (
            f"Usable after {len(fixes)} fix{'es' if len(fixes) != 1 else ''}: "
            + "; ".join(c.short for c in fixes[:3])
            + "."
        )
        readiness = "needs_work"
    else:
        readiness = "ready"
        verdict = "Ready to analyse: nothing found that would distort results."
    return AnalystReview(
        readiness=readiness,
        verdict=verdict,
        strengths=_strengths(result, concerns)[:MAX_POINTS],
        concerns=[c.text for c in concerns][: MAX_POINTS + 2],
        cannot_conclude=_cannot_conclude(result)[:MAX_POINTS],
    )


def _concerns(result: AnalysisResult) -> list[Concern]:
    out: list[Concern] = []
    n = result.row_count
    if n < SMALL_SAMPLE:
        out.append(
            Concern(
                3,
                f"only {n} rows",
                f"Only {n} rows: averages and rates will move a lot with a few more rows. Describe, don't model, "
                "and report ranges rather than single numbers.",
            )
        )
    for outcome, column, detail in leaks(result):
        out.append(
            Concern(
                3,
                f"{column} may leak {outcome}",
                f"{column} almost perfectly separates {outcome} ({detail}). Check it isn't recorded after, or "
                f"derived from, {outcome}; if it is, any model using it will look far better than it is.",
            )
        )
    for m in result.missing_dependencies:
        if m.related:
            out.append(
                Concern(
                    3,
                    f"gaps in {m.column} aren't random",
                    f"{m.column} is missing in {_pct(m.missing_share)} of rows, and not at random: "
                    f"{m.related[0].detail}. Dropping those rows would bias every result towards the rows "
                    "that answered; impute with that pattern in mind, or keep a 'was missing' flag.",
                )
            )
    for v in result.variables:
        bad = suspicious_values(v)
        if bad and v.outliers:
            values = ", ".join(f"{r.value:g}" for r in bad[:3])
            out.append(
                Concern(
                    3,
                    f"{v.name} holds entry errors",
                    f"{v.name} holds values that look like entry errors ({values}). With them its mean is "
                    f"{v.outliers.mean_all:,.4g}, without them {v.outliers.mean_without:,.4g}: correct or remove "
                    "them before quoting any average.",
                )
            )
    if result.duplicates and result.duplicates.count:
        d = result.duplicates
        out.append(
            Concern(
                2 if d.share >= 1 else 1,
                f"{d.count} duplicate rows",
                f"{d.count:,} rows ({_pct(d.share)}) are exact copies. They're left out here, but find out whether "
                "they're double entries or genuine repeats (the same order placed twice) before deduplicating "
                "the source.",
            )
        )
    for column, partner, r_all, r_without in outlier_driven(result):
        out.append(
            Concern(
                3 if abs(r_all - r_without) >= MAJOR_SHIFT_R else 2,
                f"the {column}–{partner} link rests on outliers",
                f"The link between {column} and {partner} depends on a few extreme rows: r is {r_all:.2f} with "
                f"them and {r_without:.2f} without. Don't quote the correlation without saying so.",
            )
        )
    copies = [c for c in result.correlations if abs(c.correlation) >= NEAR_COPY_R]
    for c in copies[:2]:
        out.append(
            Concern(
                2,
                f"{c.column_a} and {c.column_b} are near copies",
                f"{c.column_a} and {c.column_b} are almost the same measure (r = {c.correlation:.2f}). Keep one; "
                "using both in a model splits their effect unpredictably.",
            )
        )
    collinear = [c for c in result.correlations if COLLINEAR_R <= abs(c.correlation) < NEAR_COPY_R]
    if collinear:
        listed = ", ".join(f"{c.column_a}–{c.column_b} ({c.correlation:.2f})" for c in collinear[:3])
        out.append(
            Concern(
                1,
                "overlapping columns",
                f"Strongly overlapping columns: {listed}. A regression can't separate their effects; pick one per "
                "pair or combine them.",
            )
        )
    for v in result.variables:
        if v.binary:
            minority = min(v.binary.positive_share, 100 - v.binary.positive_share)
            if minority < LOPSIDED:
                out.append(
                    Concern(
                        2,
                        f"{v.name} is lopsided",
                        f"{v.name} is lopsided: the smaller group is {_pct(minority)} of rows. A model that always "
                        "guesses the common value looks accurate while being useless; judge by recall and AUC.",
                    )
                )
    sparse = [v for v in result.variables if v.missing_share >= SPARSE_SHARE and v.kind != "constant"]
    if sparse:
        listed = ", ".join(f"{v.name} ({_pct(v.missing_share)})" for v in sparse[:3])
        out.append(Concern(2, "sparse columns", f"Mostly empty columns: {listed}. Too sparse to lean on."))
    gaps = {
        r.column_a: r for r in result.statistics.rank_correlations
        if r.pearson is not None and abs(r.spearman - r.pearson) >= NONLINEAR_GAP
    }  # fmt: skip
    for r in list(gaps.values())[:2]:
        out.append(
            Concern(
                1,
                "curved relationship",
                f"{r.column_a} and {r.column_b} rank together more strongly than they line up (Spearman "
                f"{r.spearman:.2f} vs Pearson {r.pearson:.2f}): the relationship is curved or outlier-hit, so a "
                "straight-line model will understate it.",
            )
        )
    skewed = [v.name for v in result.variables if v.skewness is not None and abs(v.skewness) >= HEAVY_SKEW]
    if skewed:
        out.append(
            Concern(
                1,
                "heavy skew",
                f"Heavily skewed: {', '.join(skewed[:3])}. Means and Pearson correlations follow the tail; use "
                "medians, ranks or a log scale.",
            )
        )
    flags = [v.name for v in result.variables if v.kind == "constant" and v.missing]
    if flags:
        out.append(
            Concern(
                1,
                "blank-as-no flags",
                f"{', '.join(flags[:3])} hold one value plus blanks: decide whether a blank means 'no' before "
                "counting them as missing.",
            )
        )
    if result.sampled:
        out.append(
            Concern(
                1,
                "a sample of the file",
                f"These figures describe a random {result.row_count:,}-row sample of {result.rows_in_file:,} rows; "
                "rare categories may be thinly represented.",
            )
        )
    return out


def _strengths(result: AnalysisResult, concerns: list[Concern]) -> list[str]:
    out = []
    cells = sum(v.count + v.missing for v in result.variables)
    filled = 100 * sum(v.count for v in result.variables) / cells if cells else 0
    if filled >= 99:
        out.append(f"Nearly complete: {_pct(filled)} of cells are filled.")
    if result.row_count >= LARGE_SAMPLE:
        out.append(f"{result.row_count:,} rows: enough for stable estimates and for holding out a test set.")
    if not any(suspicious_values(v) for v in result.variables) and not (result.duplicates and result.duplicates.count):
        out.append("No duplicate rows and no values that look like entry errors.")
    signals = [
        b for b in result.breakdowns if b.p_value is not None and b.p_value < SIGNIFICANT and b.eta_squared >= 0.14
    ]
    for b in sorted(signals, key=lambda b: -b.eta_squared)[:2]:
        out.append(
            f"A clear signal: {b.category} explains {b.eta_squared:.0%} of {b.value} "
            f"(median {b.groups[0].box.median:g} for {b.groups[0].label} vs {b.groups[-1].box.median:g} "
            f"for {b.groups[-1].label})."
        )
    strong = [c for c in result.correlations if 0.5 <= abs(c.correlation) < NEAR_COPY_R]
    if strong:
        c = max(strong, key=lambda c: abs(c.correlation))
        out.append(f"A strong link to explore: {c.column_a} and {c.column_b} (r = {c.correlation:.2f}).")
    long_series = [t for t in result.time_series if t.points >= SHORT_SERIES]
    if long_series:
        t = long_series[0]
        out.append(f"A usable time axis: {t.points} {t.frequency} periods along {t.date_column}.")
    if not out:
        out.append("The file loads cleanly and every column has a clear type.")
    return out


def _cannot_conclude(result: AnalysisResult) -> list[str]:
    out = []
    top = max(
        (b for b in result.breakdowns if b.p_value is not None and b.p_value < SIGNIFICANT),
        key=lambda b: b.eta_squared,
        default=None,
    )
    if top is not None:
        out.append(
            f"Cause and effect. {top.category} explains {top.eta_squared:.0%} of {top.value}, but this is "
            f"observational data: {top.category} may stand in for other differences between those groups."
        )
    elif result.correlations:
        c = max(result.correlations, key=lambda c: abs(c.correlation))
        out.append(
            f"Cause and effect. {c.column_a} and {c.column_b} move together (r = {c.correlation:.2f}); that "
            "doesn't say which drives which, or whether a third factor drives both."
        )
    else:
        out.append("Cause and effect: nothing here comes from a controlled experiment.")
    if not result.time_series:
        out.append("Trends, growth or seasonality: the file has no time axis to read them from.")
    elif all(t.points < SHORT_SERIES for t in result.time_series):
        out.append(
            f"Seasonality: under {SHORT_SERIES} periods of history isn't enough to tell a repeating pattern from noise."
        )
    for v in result.variables:
        if v.binary:
            idx = v.binary.values.index(v.binary.positive) if v.binary.positive in v.binary.values else 0
            events = v.binary.counts[idx]
            if events < EVENTS_PER_PREDICTOR * 5:
                out.append(
                    f"Reliable predictions of {v.name}: there are only {events} '{v.binary.positive}' rows to "
                    "learn from."
                )
    tests = (
        len(result.breakdowns)
        + len(result.crosstabs)
        + len(result.statistics.rank_correlations)
        + len(result.correlations)
    )
    if tests >= 10:
        out.append(
            f"Every 'significant' result at face value: {tests} comparisons were tested, so a few will pass by "
            "chance. p-values are adjusted, but treat borderline ones (0.01 to 0.05) as leads to confirm."
        )
    if result.sampled:
        out.append("Exact totals or counts for the whole file: these figures describe a sample.")
    if result.row_count < SMALL_SAMPLE:
        out.append("Precise percentages: with this few rows one record moves a rate by a point or more.")
    return out


# ---------------------------------------------------------------------------
# Each suggested analysis
# ---------------------------------------------------------------------------


def assess(rec: Recommendation, result: AnalysisResult) -> Recommendation:
    """Set how ready the data is for this analysis and what could make its answer wrong."""
    profiles = {v.name: v for v in result.variables}
    risks: list[str] = []
    weak = False
    target = rec.columns[0] if rec.columns else ""
    p = profiles.get(target)

    if rec.analysis in ("logistic_regression", "classification", "linear_regression"):
        for outcome, column, detail in leaks(result):
            if outcome == target:
                risks.append(f"Possible leakage: {column} almost perfectly separates {target} ({detail}).")
        k = predictors(result, target)
        if p is not None and p.binary:
            events = min(p.binary.counts)
            if k and events / k < EVENTS_PER_PREDICTOR:
                risks.append(
                    f"Only {events} rows in the smaller group for {k} candidate predictors (under "
                    f"{EVENTS_PER_PREDICTOR} per predictor): expect overfitting; use fewer columns or regularise."
                )
            top = p.compared[0] if p.compared else None
            weak = top is None or top.p_value is None or top.p_value >= SIGNIFICANT or abs(top.effect) < 0.1
            if weak:
                risks.append(f"No column differs clearly between the {target} groups: expect little predictive power.")
        elif k and result.row_count / k < ROWS_PER_PREDICTOR:
            risks.append(
                f"{result.row_count} rows for {k} candidate predictors: under {ROWS_PER_PREDICTOR} rows each, so "
                "coefficients will be unstable."
            )
        own = next((m for m in result.missing_dependencies if m.related and m.column == target), None)
        if own:
            risks.append(
                f"{target} itself is missing in {_pct(own.missing_share)} of rows, not at random "
                f"({own.related[0].detail}): a model trained on the rest won't represent those rows."
            )
        dirty = [v.name for v in result.variables if v.name != target and suspicious_values(v)]
        if dirty:
            risks.append(
                f"Fix the entry errors in {', '.join(dirty[:3])} first: they'd distort any model that uses "
                f"{'it' if len(dirty) == 1 else 'them'}."
            )
        gappy = [m for m in result.missing_dependencies if m.related and m.column != target]
        if gappy:
            risks.append(f"Gaps in {gappy[0].column} aren't random; dropping incomplete rows would bias the model.")
        if rec.analysis == "linear_regression" and p is not None:
            if p.skewness is not None and abs(p.skewness) >= 1 and not any("skewed" in c for c in rec.check_first):
                risks.append(f"{target} is skewed ({p.skewness:.2f}): residuals won't be normal on the raw scale.")
            for column, partner, r_all, r_without in outlier_driven(result):
                if target in (column, partner):
                    risks.append(
                        f"Its link with {partner if column == target else column} is outlier-driven "
                        f"(r {r_all:.2f} with, {r_without:.2f} without)."
                    )
    elif rec.analysis == "time_series":
        ts = next((t for t in result.time_series if t.column == target), None)
        if ts:
            if ts.points < SHORT_SERIES:
                risks.append(f"Only {ts.points} periods: too short to separate trend from seasonality.")
                weak = True
            if ts.stationary is False:
                risks.append("The level drifts: a model fitted to its average will be biased.")
        risks.append("A forecast only extends the past; it can't see price changes, launches or shocks.")
    elif rec.analysis == "group_comparison" and len(rec.columns) >= 2:
        b = next((b for b in result.breakdowns if b.category == rec.columns[0] and b.value == rec.columns[1]), None)
        if b:
            sizes = [g.box.n for g in b.groups]
            if min(sizes) < MIN_GROUP_ROWS:
                small = b.groups[sizes.index(min(sizes))]
                risks.append(f"'{small.label}' has only {small.box.n} rows: its median is fragile.")
            if max(sizes) >= UNEVEN_GROUPS * max(1, min(sizes)):
                risks.append("Group sizes are very uneven: compare medians, not totals.")
        risks.append(
            f"Groups differ in more than {rec.columns[0]}: the gap may come from something else that varies "
            "between them."
        )
    elif rec.analysis == "correlation" and len(rec.columns) >= 2:
        pair = set(rec.columns[:2])
        for column, partner, r_all, r_without in outlier_driven(result):
            if {column, partner} == pair:
                risks.append(f"Outlier-driven: r is {r_all:.2f} with the extreme rows, {r_without:.2f} without.")
        for r in result.statistics.rank_correlations:
            if (
                {r.column_a, r.column_b} == pair
                and r.pearson is not None
                and abs(r.spearman - r.pearson) >= NONLINEAR_GAP
            ):
                risks.append(f"Curved: Spearman {r.spearman:.2f} vs Pearson {r.pearson:.2f}.")
        risks.append("Correlation says nothing about which drives which.")
    elif rec.analysis == "clustering":
        risks.append("k-means finds groups even in data that has none: check the groups are stable and mean something.")
    elif rec.analysis == "distribution":
        risks.append("Averages of this column overstate the typical value.")

    if rec.analysis in ("data_quality", "outliers"):
        readiness = "needs_work"
    elif weak:
        readiness = "weak"
    elif risks and rec.analysis not in ("correlation", "time_series", "group_comparison", "clustering", "distribution"):
        readiness = "needs_work"
    elif any(r.startswith(("Outlier-driven", "Only", "'")) for r in risks):
        readiness = "needs_work"
    else:
        readiness = "ready"
    return rec.model_copy(update={"readiness": readiness, "risks": risks[:4]})
