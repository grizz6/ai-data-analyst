"""What this dataset could be used for next, and which of that serves a stated goal.

The app explores data; it doesn't run these analyses. `recommend` reads the
finished exploration and lists the analyses the data supports, each with the
reason taken from the data ("churned is yes/no, 35% Yes; tenure_months
differs most"), what to check or fix first, and where in the exploration to look.

`plan_for_goal` takes a business goal in plain words and orders a few of
those analyses into a plan. A language model picks and explains the steps
when one is configured; it can only choose from the listed analyses, and
the usual check rejects any number it didn't get from the results. Without a
model, keyword rules make the plan.
"""

import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.models.schemas import (
    AnalysisResult,
    ModelPlan,
    PlanResponse,
    PlanStep,
    Recommendation,
    RecommendationAction,
)
from app.services import explanation, review
from app.services.grounding import ungrounded_numbers
from app.services.llm_client import LLMClient, LLMError
from app.services.semantics import name_words

logger = logging.getLogger(__name__)

MAX_BINARY_TARGETS = 3
MAX_TIME_SERIES = 3
MAX_REGRESSION_TARGETS = 2
MAX_GROUP_COMPARISONS = 3
# Past the first series, one without this much trend or seasonality ranks low.
MIN_SERIES_STRENGTH = 0.3
MAX_PLAN_STEPS = 5
MAX_CHECKS = 3
MIN_SEGMENT_ROWS = 50
MIN_PLAN_STEPS = 3
MAX_GOAL_CHARS = 1_000
SIGNIFICANT = 0.05
ERROR_CAUSE_WORDS = ("placeholder", "entry error", "typo", "entered correctly", "unit mix-up")


def recommend(result: AnalysisResult) -> list[Recommendation]:
    recs: list[Recommendation] = []
    profiles = {v.name: v for v in result.variables}

    serious = [q for q in result.quality_issues if q.severity in ("error", "warning")]
    if serious:
        recs.append(
            _rec(
                "data_quality",
                "data_quality",
                "Fix data quality first",
                f"{len(serious)} issue{'s' if len(serious) != 1 else ''} to check before trusting any result, "
                f"starting with: {serious[0].message}",
                [q.column for q in serious if q.column][:5],
                RecommendationAction(tab="quality", label="See data quality"),
                90,
                [q.message for q in serious[1:4]],
            )
        )

    for v in result.variables:
        if v.outliers is None:
            continue
        suspicious = [r for r in v.outliers.rows if any(w in r.cause for w in ERROR_CAUSE_WORDS)]
        if suspicious:
            values = ", ".join(f"{r.value:g}" for r in suspicious[:3])
            recs.append(
                _rec(
                    f"outliers:{v.name}",
                    "outliers",
                    f"Check suspicious values in {v.name}",
                    f"{len(suspicious)} value{'s' if len(suspicious) != 1 else ''} in {v.name} look like entry "
                    f"errors ({values}); with every outlier its mean is {v.outliers.mean_all:,.4g}, "
                    f"without them {v.outliers.mean_without:,.4g}.",
                    [v.name],
                    RecommendationAction(tab="variables", column=v.name, label=f"See {v.name}"),
                    85,
                    ["Confirm or correct each value in the outlier table, then decide to drop, cap or keep them."],
                )
            )

    targets = {t.column for t in result.model_targets}
    binaries = [v for v in result.variables if v.kind == "binary" and v.binary][:MAX_BINARY_TARGETS]
    for v in binaries:
        assert v.binary is not None
        top = v.compared[0] if v.compared else None
        why = f"{v.name} is yes/no ({v.binary.positive_share:g}% {v.binary.positive})"
        real = top is not None and top.p_value is not None and top.p_value < SIGNIFICANT
        if top is not None and real:
            why += f"; {top.column} differs most between the two groups ({top.detail})"
        else:
            why += "; no other column differs clearly between its two groups yet"
        why += ". Logistic regression or another classifier would estimate each row's chance and what drives it."
        checks = []
        minority = min(v.binary.positive_share, 100 - v.binary.positive_share)
        if minority < 20:
            checks.append(
                f"The smaller group is only {minority:g}% of rows: judge models by recall and AUC, not accuracy."
            )
        checks += _input_checks(result, exclude=v.name)
        score = (70 + 20 * abs(top.effect) if real and top else 45) + (10 if v.name in targets else 0)
        recs.append(
            _rec(
                f"logistic:{v.name}",
                "logistic_regression",
                f"Predict {v.name} (yes/no)",
                why,
                [v.name] + ([top.column] if top else []),
                RecommendationAction(tab="variables", column=v.name, label=f"See {v.name}"),
                score,
                checks,
            )
        )

    for i, ts in enumerate(result.time_series[:MAX_TIME_SERIES]):
        strength = max(ts.seasonal_strength or 0, ts.trend_strength or 0)
        score = 55 + 25 * strength if i == 0 or strength >= MIN_SERIES_STRENGTH else 30
        parts = [f"{ts.points} {ts.frequency} periods of {ts.column} along {ts.date_column}"]
        if ts.seasonal_strength is not None and ts.seasonal_strength >= 0.4:
            parts.append(f"a repeating pattern every {ts.seasonal_period} periods")
        checks = []
        if ts.filled_gaps:
            checks.append(f"{ts.filled_gaps} periods have no data; decide how to fill them before forecasting.")
        if ts.stationary is False:
            checks.append("Its level drifts (not stationary): difference it or model the trend first.")
        if ts.points < 24:
            checks.append(f"Only {ts.points} periods: too short for a reliable seasonal forecast.")
        recs.append(
            _rec(
                f"time_series:{ts.column}",
                "time_series",
                f"Forecast {ts.column}",
                ", ".join(parts) + ". A forecasting model (exponential smoothing or ARIMA) could project it forward.",
                [ts.column, ts.date_column],
                RecommendationAction(tab="time", label="See it over time"),
                score,
                checks,
            )
        )

    strongest = _strongest_correlations(result)
    numeric_targets = sorted(
        (t.column for t in result.model_targets if (p := profiles.get(t.column)) and p.kind in ("number", "count")),
        key=lambda c: -abs(strongest[c][1]) if c in strongest else 0,
    )[:MAX_REGRESSION_TARGETS]
    for t in result.model_targets:
        profile = profiles.get(t.column)
        if profile is None or profile.kind == "binary":
            continue
        if profile.kind in ("number", "count") and t.column in numeric_targets:
            partner = strongest.get(t.column)
            why = f"{t.column} is numeric"
            if partner:
                why += f"; its strongest link is {partner[0]} (r = {partner[1]:.2f})"
            why += ". Linear regression or tree models would estimate it and rank what drives it."
            checks = []
            if profile.skewness is not None and abs(profile.skewness) >= 1:
                checks.append(f"{t.column} is skewed ({profile.skewness:.2f}): try a log scale for linear regression.")
            if profile.outliers and profile.outliers.iqr_count:
                checks.append(f"{profile.outliers.iqr_count} outliers in {t.column} would pull a linear fit.")
            checks += _input_checks(result, exclude=t.column)
            recs.append(
                _rec(
                    f"regression:{t.column}",
                    "linear_regression",
                    f"Explain and predict {t.column}",
                    why,
                    [t.column] + ([partner[0]] if partner else []),
                    RecommendationAction(tab="variables", column=t.column, label=f"See {t.column}"),
                    60 + 20 * (abs(partner[1]) if partner else 0),
                    checks,
                )
            )
        elif profile.kind == "category":
            smallest = min(profile.categories, key=lambda c: c.share) if profile.categories else None
            checks = []
            if smallest and smallest.share < 5:
                checks.append(f"The rarest class, '{smallest.value}', is {smallest.share:g}% of rows.")
            recs.append(
                _rec(
                    f"classification:{t.column}",
                    "classification",
                    f"Predict {t.column} ({profile.distinct} classes)",
                    f"{t.column} has {profile.distinct} categories; a classifier would predict which one a row "
                    "belongs to.",
                    [t.column],
                    RecommendationAction(tab="variables", column=t.column, label=f"See {t.column}"),
                    50,
                    checks + _input_checks(result, exclude=t.column),
                )
            )

    numeric = [v for v in result.variables if v.kind == "number"]
    if len(numeric) >= 3 and result.row_count >= MIN_SEGMENT_ROWS:
        names = [v.name for v in numeric[:5]]
        spans = [v.max - v.min for v in numeric if v.max is not None and v.min is not None]
        checks = []
        if spans and min(spans) > 0 and max(spans) / min(spans) >= 10:
            checks.append("The columns are on very different scales: standardize them first.")
        skewed_names = [v.name for v in numeric if v.skewness is not None and abs(v.skewness) >= 1]
        if skewed_names:
            checks.append(f"Skewed columns ({', '.join(skewed_names[:3])}) can dominate distances; consider logs.")
        recs.append(
            _rec(
                "segmentation",
                "clustering",
                "Look for segments (clustering)",
                f"{len(numeric)} numeric columns ({', '.join(names)}) could define groups of similar rows, "
                "for example with k-means.",
                names,
                RecommendationAction(tab="relationships", label="See relationships"),
                40,
                checks,
            )
        )

    groups = [g for g in result.statistics.group_differences if g.p_adjusted is not None and g.p_adjusted < SIGNIFICANT]
    for g in sorted(groups, key=lambda d: d.eta_squared, reverse=True)[:MAX_GROUP_COMPARISONS]:
        recs.append(
            _rec(
                f"groups:{g.group_column}:{g.value_column}",
                "group_comparison",
                f"Compare {g.value_column} across {g.group_column}",
                f"{g.group_column} explains {g.eta_squared:.0%} of the variation in {g.value_column}: "
                f"highest in {g.highest_group}, lowest in {g.lowest_group}.",
                [g.group_column, g.value_column],
                RecommendationAction(tab="relationships", label="See relationships"),
                50 + 40 * g.eta_squared,
                ["An ANOVA or Kruskal-Wallis test confirms it; check each group has enough rows."],
            )
        )

    if result.correlations:
        pair = max(result.correlations, key=lambda c: abs(c.correlation))
        recs.append(
            _rec(
                "correlation",
                "correlation",
                f"Look at how {pair.column_a} and {pair.column_b} move together",
                f"The strongest link in the file: r = {pair.correlation:.2f} over {pair.n} rows.",
                [pair.column_a, pair.column_b],
                RecommendationAction(tab="relationships", label="See relationships"),
                45 + 30 * abs(pair.correlation),
                ["Correlation isn't cause: look at the scatter plot for curves, clusters or outliers driving it."],
            )
        )

    skewed = [v for v in result.variables if v.skewness is not None and abs(v.skewness) >= 1 and v.kind == "number"]
    for v in skewed[:2]:
        recs.append(
            _rec(
                f"distribution:{v.name}",
                "distribution",
                f"Mind the shape of {v.name}",
                f"{v.name} is skewed (skewness {v.skewness:.2f}): report its median ({v.median:,.4g}) rather than its "
                f"mean ({v.mean:,.4g}).",
                [v.name],
                RecommendationAction(tab="variables", column=v.name, label=f"See {v.name}"),
                40,
                ["Use a log scale (or a rank-based method) before any linear model."],
            )
        )

    recs = [review.assess(r, result) for r in recs]
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs


def _rec(
    rec_id: str,
    analysis: str,
    title: str,
    why: str,
    columns: list[str],
    action: RecommendationAction,
    score: float,
    check_first: list[str] | None = None,
) -> Recommendation:
    return Recommendation(
        id=rec_id,
        analysis=analysis,
        title=title,
        why=why,
        columns=columns,
        action=action,
        score=round(score, 2),
        check_first=(check_first or [])[:MAX_CHECKS],
    )


def _input_checks(result: AnalysisResult, exclude: str) -> list[str]:
    """What to sort out in the other columns before using them to explain or predict one."""
    checks = []
    gappy = [v for v in result.variables if v.name != exclude and v.missing_share >= 5 and v.kind != "identifier"]
    if gappy:
        listed = ", ".join(f"{v.name} ({v.missing_share:g}%)" for v in gappy[:3])
        checks.append(f"Missing values to handle: {listed}.")
    twins = [c for c in result.correlations if abs(c.correlation) >= 0.8 and exclude not in (c.column_a, c.column_b)]
    if twins:
        c = twins[0]
        checks.append(
            f"{c.column_a} and {c.column_b} carry nearly the same information (r = {c.correlation:.2f}); "
            "use one of them."
        )
    return checks


def _strongest_correlations(result: AnalysisResult) -> dict[str, tuple[str, float]]:
    best: dict[str, tuple[str, float]] = {}
    for c in result.correlations:
        for a, b in ((c.column_a, c.column_b), (c.column_b, c.column_a)):
            if a not in best or abs(c.correlation) > abs(best[a][1]):
                best[a] = (b, c.correlation)
    return best


# ---------------------------------------------------------------------------
# Plans for a stated goal
# ---------------------------------------------------------------------------

GOAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "logistic_regression": (
        "churn",
        "retain",
        "retention",
        "cancel",
        "leave",
        "convert",
        "conversion",
        "default",
        "fraud",
        "click",
        "buy",
        "purchase",
        "whether",
        "yes",
        "approve",
        "risk",
        "classify",
        "likelihood",
        "probability",
    ),
    "classification": ("classify", "category", "which type", "which kind", "label", "predict which"),
    "linear_regression": (
        "predict",
        "estimate",
        "price",
        "revenue",
        "sales",
        "spend",
        "amount",
        "how much",
        "value",
        "cost",
        "driver",
        "drive",
        "factor",
        "influence",
        "affect",
        "impact",
        "explain",
        "why",
    ),
    "time_series": (
        "forecast",
        "future",
        "next month",
        "next year",
        "next quarter",
        "trend",
        "over time",
        "season",
        "growth",
        "demand",
        "plan",
        "budget",
        "monthly",
        "weekly",
        "daily",
    ),
    "clustering": ("segment", "group", "cluster", "persona", "types of", "target", "audience", "similar"),
    "group_comparison": ("compare", "difference", "versus", "vs", "region", "best", "worst", "which", "between"),
    "correlation": ("relationship", "related", "correlat", "together", "link", "connected", "driver", "factor"),
    "data_quality": ("clean", "quality", "missing", "error", "wrong", "trust", "accurate", "fix"),
    "outliers": ("outlier", "anomal", "unusual", "strange", "error", "fraud", "spike"),
    "distribution": ("typical", "average", "distribution", "spread", "range", "normal"),
}

PLAN_SYSTEM_PROMPT = f"""\
You are a senior data analyst turning a business goal into a short, honest plan of
analyses on one dataset. An automated exploration has already run; you are given its
results ("facts", including a critical review of the data) and the analyses this data
supports ("options"), each with an id, the reason it fits, how ready the data is for it,
its risks and what to check first. Be critical: say what could make each step mislead.

{explanation.GROUND_RULES}

Choose the {MIN_PLAN_STEPS} to {MAX_PLAN_STEPS} options that best serve the goal, in the order to do them.
Start with data quality or suspicious values when the options include them and they
could distort the answer. Use only ids from the options.

The JSON object must have exactly one key, "steps": a list of objects with "id" (copied
from the options) and "why" (one or two sentences linking that analysis to the goal,
naming the columns involved and the main risk to its answer). When the file can't answer part of the goal (a column
it would need doesn't exist), add a key "note" with one sentence saying so."""


def rule_plan(
    result: AnalysisResult, goal: str, *, configured: bool = False, reason: str | None = None
) -> PlanResponse:
    recs = result.recommendations or recommend(result)
    text = goal.lower()
    goal_words = set(name_words(goal))
    scored = []
    for rec in recs:
        keywords = GOAL_KEYWORDS.get(rec.analysis, ())
        hits = sum(1 for k in keywords if (k in goal_words if " " not in k and len(k) <= 3 else k in text))
        relevance = hits + max((_mention(c, text) for c in rec.columns), default=0)
        scored.append((relevance, rec))
    chosen = [r for rel, r in sorted(scored, key=lambda x: (x[0], x[1].score), reverse=True) if rel > 0]
    note = None
    if not chosen:
        note = "Nothing in this file matched the goal's words, so these are the strongest analyses for the file."
    if len(chosen) < MIN_PLAN_STEPS:
        chosen += [r for r in recs if r not in chosen][: MIN_PLAN_STEPS - len(chosen)]
    chosen = chosen[:MAX_PLAN_STEPS]
    # Fixing the data comes first whenever it made the plan.
    chosen.sort(key=lambda r: 0 if r.analysis in ("data_quality", "outliers") else 1)
    steps = [
        PlanStep(
            id=r.id,
            title=r.title,
            why=r.why,
            action=r.action,
            readiness=r.readiness,
            risks=r.risks,
            check_first=r.check_first,
        )
        for r in chosen
    ]
    return PlanResponse(
        goal=goal, steps=steps, note=note, configured=configured, source="rule_based", fallback_reason=reason
    )


def _mention(column: str, text: str) -> int:
    """3 when the goal names the column, 2 when it uses a word from its name ("spend" for monthly_spend)."""
    if column.lower() in text or " ".join(name_words(column)) in text:
        return 3
    words = [w for w in name_words(column) if len(w) > 3]
    return 2 if any(re.search(rf"\b{re.escape(w)}", text) for w in words) else 0


async def plan_for_goal(result: AnalysisResult, goal: str, client: LLMClient | None = None) -> PlanResponse:
    goal = goal.strip()[:MAX_GOAL_CHARS]
    if not explanation.is_llm_configured():
        return rule_plan(result, goal)
    recs = result.recommendations or recommend(result)
    if not recs:
        return rule_plan(result, goal, configured=True)

    client = client or explanation.make_client()
    facts = explanation.build_facts(result)
    options = [
        {
            "id": r.id,
            "analysis": r.analysis,
            "title": r.title,
            "why_it_fits": r.why,
            "readiness": r.readiness,
            "risks": r.risks,
            "check_first": r.check_first,
        }
        for r in recs
    ]
    payload: dict[str, Any] = {"goal": goal, "options": options, "facts": facts}
    try:
        reply = await client.chat_json(PLAN_SYSTEM_PROMPT, json.dumps(payload, default=str))
        parsed = ModelPlan.model_validate(reply.data)
    except LLMError as exc:
        return _plan_fallback(result, goal, f"model call failed: {exc}")
    except ValidationError:
        return _plan_fallback(result, goal, "model reply was missing the steps")

    by_id = {r.id: r for r in recs}
    steps: list[PlanStep] = []
    for step in parsed.steps:
        rec = by_id.get(step.id)
        if rec is None or any(s.id == rec.id for s in steps):
            continue
        steps.append(
            PlanStep(
                id=rec.id,
                title=rec.title,
                why=step.why,
                action=rec.action,
                readiness=rec.readiness,
                risks=rec.risks,
                check_first=rec.check_first,
            )
        )
    if not steps:
        return _plan_fallback(result, goal, "model chose no analysis the app can run")
    steps = steps[:MAX_PLAN_STEPS]

    invented = ungrounded_numbers(" ".join(s.why for s in steps), {"facts": facts, "options": options, "goal": goal})
    if invented:
        return _plan_fallback(result, goal, f"model wrote numbers not in the analysis: {', '.join(invented[:5])}")
    note = parsed.note or None
    invented_note = ungrounded_numbers(note or "", {"facts": facts, "options": options, "goal": goal})
    return PlanResponse(
        goal=goal, steps=steps, note=None if invented_note else note, configured=True, source="llm", model=reply.model
    )


def _plan_fallback(result: AnalysisResult, goal: str, reason: str) -> PlanResponse:
    logger.warning("LLM plan fell back to rules: %s", reason)
    return rule_plan(result, goal, configured=True, reason=reason)
