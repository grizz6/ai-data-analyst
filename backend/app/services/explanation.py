"""
Explanation layer.

All numbers and charts come from Pandas/Plotly in other services. This layer
only turns those results into readable text, in one of two ways:

- With a model configured (ADA_LLM_API_KEY), the model gets the computed
  facts as JSON and writes the explanation. Its reply must be valid JSON in
  the expected shape, and every number in it must appear in the facts
  (grounding.py). If any of that fails, or the provider is down, the
  rule-based text below is used instead and the reason is recorded.
- Without a model, the text is written from rules, so it is deterministic and
  every figure in it is copied from the analysis result.
"""

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.config import settings
from app.models.schemas import (
    AnalysisResult,
    Explanation,
    ModelExplanation,
)
from app.services.grounding import ungrounded_numbers
from app.services.llm_client import LLMClient, LLMError

logger = logging.getLogger(__name__)

HIGHLIGHT_CATEGORIES = ("correlation", "trend", "categorical")
MAX_RECOMMENDATIONS = 6
MAX_FACT_VARIABLES = 40
MAX_STORY_POINTS = 5
# A value seen in fewer rows than this can point at one person (an email, an ID
# number, a name), so it is never sent to the model.
MIN_SHARED_ROWS = 3
REDACTED = f"[a value from fewer than {MIN_SHARED_ROWS} rows]"
# Shorter private values ("A", "12") are only redacted where they are the whole
# string; inside a sentence they would match unrelated text.
MIN_REDACT_INSIDE_TEXT = 3

GROUND_RULES = """\
Rules you must follow:
- Use only the facts in the JSON you are given. Do not use outside knowledge about the data.
- Never calculate. Do not add, subtract, average, compare as a ratio or percentage, or round
  to a new figure. Every number you write must appear in the facts exactly as given
  (rounding a given number for readability is fine).
- When the facts don't answer something, say so plainly instead of guessing.
- Write for a non-technical reader. Short sentences. No markdown.
- Reply with a single JSON object and nothing else."""

EXPLAIN_SYSTEM_PROMPT = f"""\
You write a short, plain-English story of what a dataset contains and what an automated
exploratory data analysis (EDA) found in it. The numbers were computed by code; your job
is only to say what they mean for someone about to work with this data.

{GROUND_RULES}

The JSON object must have exactly these keys:
- "dataset_overview": 2 to 3 sentences: what the file holds (rows, kinds of columns) and how
  complete and clean it is.
- "analysis_summary": 3 to 5 sentences on what the data tells you: the most notable
  distributions, outliers, missing-value patterns, relationships and group differences.
- "recommendations": a list of up to 5 short things to check or fix in the data before using it.
- "chart_explanations": a list of objects with "chart_id" (copied from the facts) and
  "explanation" (one or two sentences on what that chart shows)."""

def is_llm_configured() -> bool:
    return settings.llm_configured


def make_client() -> LLMClient:
    return LLMClient(
        api_key=settings.llm_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        fallback_models=settings.llm_fallback_models,
    )


def build_facts(result: AnalysisResult) -> dict[str, Any]:
    """Everything the model may talk about. It is not allowed to go beyond this.

    Values that belong to only a row or two, and every value of a free-text or
    ID column, are removed first: the model gets the file's shape, not its people.
    """
    private = _row_level_values(result)
    return _redact(_all_facts(result), private, frozenset(c.name for c in result.columns))


def _row_level_values(result: AnalysisResult) -> set[str]:
    private: set[str] = set()
    for summary in result.categorical_summaries:
        for top in summary.top_values:
            if int(top.get("count") or 0) < MIN_SHARED_ROWS:
                private.add(str(top.get("value")))
    for v in result.variables:
        row_level = v.kind in ("text", "identifier")
        for c in v.categories:
            if row_level or c.count < MIN_SHARED_ROWS:
                private.add(c.value)
    for b in result.breakdowns:
        private.update(g.label for g in b.groups if g.box.n < MIN_SHARED_ROWS)
    return private


def _redact(value: Any, private: set[str], keep: frozenset[str]) -> Any:
    """A copy of `value` with private strings dropped from lists or replaced in text."""
    if isinstance(value, dict):
        if str(value.get("value")) in private and value.get("value") not in keep:
            return None
        return {k: _redact(v, private, keep) for k, v in value.items()}
    if isinstance(value, list):
        items = (_redact(v, private, keep) for v in value)
        return [v for v in items if v is not None]
    if isinstance(value, str) and value not in keep:
        if value in private:
            return REDACTED
        for secret in private:
            if len(secret) >= MIN_REDACT_INSIDE_TEXT and secret in value and secret not in keep:
                value = value.replace(secret, REDACTED)
        return value
    return value


def _all_facts(result: AnalysisResult) -> dict[str, Any]:
    return {
        "file": {
            "name": result.filename,
            "sheet": result.sheet_name,
            "rows_after_cleaning": result.row_count,
            "rows_in_file": result.rows_in_file,
            "analyzed_a_random_sample": result.sampled,
            "columns_after_cleaning": result.column_count,
        },
        "columns": [
            {
                "name": c.name,
                "type": c.dtype,
                "missing_values": c.null_count,
                "missing_percent": c.null_pct,
                "distinct_values": c.unique_count,
                "identifier": c.is_identifier,
            }
            for c in result.columns
        ],
        "quality_issues": [
            {"severity": q.severity, "category": q.category, "message": q.message} for q in result.quality_issues
        ],
        "cleaning_actions": [a.description for a in result.cleaning_actions],
        "numeric_summaries": [s.model_dump() for s in result.numeric_summaries],
        "top_categories": [{"column": c.column, "top_values": c.top_values[:5]} for c in result.categorical_summaries],
        "correlations": [p.model_dump() for p in result.correlations],
        "trends": [t.model_dump() for t in result.trends],
        "findings": [i.message for i in result.rule_insights],
        "time_series": [
            {
                "column": t.column,
                "frequency": t.frequency,
                "periods": t.points,
                "summary": t.summary,
            }
            for t in result.time_series
        ],
        "statistical_tests": {
            "distributions": [
                {
                    "column": d.column,
                    "skewness": d.skewness,
                    "shape": d.shape,
                    "outliers_beyond_3_sd": d.zscore_outliers,
                }
                for d in result.statistics.distributions[:8]
            ],
            "rank_correlations": [r.model_dump() for r in result.statistics.rank_correlations[:5]],
            "categorical_associations": [a.model_dump() for a in result.statistics.categorical_associations[:5]],
            "group_differences": [g.model_dump() for g in result.statistics.group_differences[:5]],
        },
        "charts": [{"chart_id": c.id, "title": c.title, "type": c.chart_type} for c in result.charts],
        "columns_profiled": [_variable_fact(v) for v in result.variables[:MAX_FACT_VARIABLES]],
        "duplicates": result.duplicates.model_dump(exclude={"groups"}) if result.duplicates else None,
        "missing_value_patterns": [
            {"column": m.column, "missing_percent": m.missing_share, "related": [r.detail for r in m.related]}
            for m in result.missing_dependencies
        ],
        "analyst_review": result.review.model_dump() if result.review else None,
        "numbers_by_group": [
            {
                "value": b.value,
                "by": b.category,
                "share_of_variation_explained": b.eta_squared,
                "highest_group": b.groups[0].label,
                "highest_median": b.groups[0].box.median,
                "lowest_group": b.groups[-1].label,
                "lowest_median": b.groups[-1].box.median,
            }
            for b in _notable_breakdowns(result)
        ],
    }


def _variable_fact(v) -> dict[str, Any]:
    fact: dict[str, Any] = {"name": v.name, "kind": v.kind, "missing_percent": v.missing_share, "distinct": v.distinct}
    if v.median is not None:
        fact.update(median=v.median, mean=v.mean, min=v.min, max=v.max, skewness=v.skewness)
    if v.outliers:
        fact["outliers_iqr"] = v.outliers.iqr_count
        fact["suspicious_values"] = [
            {"value": r.value, "likely_cause": r.cause} for r in v.outliers.rows if "genuine" not in r.cause
        ][:3]
    if v.binary:
        fact["split"] = {"value": v.binary.positive, "percent": v.binary.positive_share}
        fact["differs_most_by"] = [c.detail for c in v.compared[:2] if c.p_value is not None and c.p_value < 0.05]
    if v.categories:
        fact["most_common"] = {"value": v.categories[0].value, "percent": v.categories[0].share}
    if v.flags:
        fact["notes"] = v.flags
    return fact


def _notable_breakdowns(result: AnalysisResult) -> list:
    real = [b for b in result.breakdowns if b.p_value is not None and b.p_value < 0.05 and b.eta_squared >= 0.06]
    return sorted(real, key=lambda b: b.eta_squared, reverse=True)[:5]


# ---------------------------------------------------------------------------
# Rule-based text: used when no model is configured, and as the fallback.
# ---------------------------------------------------------------------------


def rule_based_explanation(
    result: AnalysisResult, *, configured: bool = False, fallback_reason: str | None = None
) -> Explanation:
    return Explanation(
        dataset_overview=_story_overview(result),
        chart_explanations=[],
        analysis_summary=" ".join(_story_points(result)) or "No strong patterns stood out in this file.",
        recommendations=_recommendations(result),
        configured=configured,
        source="rule_based",
        fallback_reason=fallback_reason,
    )


KIND_WORDS = {
    "number": "numeric",
    "count": "count",
    "binary": "yes/no",
    "category": "category",
    "date": "date",
    "text": "free-text",
    "identifier": "ID",
    "constant": "constant",
}


def _story_overview(result: AnalysisResult) -> str:
    kinds: dict[str, int] = {}
    for v in result.variables:
        kinds[v.kind] = kinds.get(v.kind, 0) + 1
    listed = ", ".join(f"{n} {KIND_WORDS.get(k, k)}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
    cells = sum(v.count + v.missing for v in result.variables)
    filled = 100 * sum(v.count for v in result.variables) / cells if cells else 100.0
    parts = [f"'{result.filename}' has {result.row_count:,} rows and {result.column_count} columns ({listed})."]
    parts.append(f"{filled:.1f}% of cells are filled.")
    if result.duplicates and result.duplicates.count:
        parts.append(f"{result.duplicates.count:,} rows are exact duplicates.")
    issues = len(result.quality_issues)
    parts.append(f"{issues} data quality issue{'s were' if issues != 1 else ' was'} flagged.")
    return " ".join(parts)


def _story_points(result: AnalysisResult) -> list[str]:
    points: list[str] = []
    for v in result.variables:
        suspicious = [
            r
            for r in (v.outliers.rows if v.outliers else [])
            if "genuine" not in r.cause and "plausible" not in r.cause
        ]
        if suspicious:
            values = ", ".join(f"{r.value:g}" for r in suspicious[:3])
            points.append(f"'{v.name}' has values that look like entry errors ({values}).")
    for m in result.missing_dependencies:
        if m.related:
            points.append(f"Gaps in '{m.column}' aren't random: {m.related[0].detail}.")
    if result.correlations:
        c = max(result.correlations, key=lambda p: abs(p.correlation))
        points.append(f"'{c.column_a}' and '{c.column_b}' move together (r = {c.correlation:.2f}).")
    for b in _notable_breakdowns(result)[:2]:
        points.append(
            f"'{b.value}' differs by '{b.category}': highest in {b.groups[0].label} "
            f"(median {b.groups[0].box.median:g}), lowest in {b.groups[-1].label} (median {b.groups[-1].box.median:g})."
        )
    for v in result.variables:
        if v.binary and v.compared and v.compared[0].p_value is not None and v.compared[0].p_value < 0.05:
            points.append(f"For '{v.name}', {v.compared[0].detail}.")
    skewed = [
        v.name for v in result.variables if v.kind == "number" and v.skewness is not None and abs(v.skewness) >= 1
    ]
    if skewed:
        points.append(f"Skewed columns ({', '.join(skewed[:3])}) are better described by their median than their mean.")
    return points[:MAX_STORY_POINTS]


def _recommendations(result: AnalysisResult) -> list[str]:
    recs: list[str] = []

    for action in result.cleaning_actions:
        if action.action == "drop_duplicates":
            recs.append(
                f"{action.rows_affected} duplicate row(s) were removed. "
                "Confirm they were not legitimate repeat records."
            )
        elif action.action == "drop_column":
            recs.append(
                f"'{action.column}' was dropped for being mostly empty. "
                "Check whether the source system is supposed to fill it."
            )
        elif action.action == "convert_numeric_text":
            recs.append(
                f"'{action.column}' arrived as text and was converted to numbers. "
                "Fix the export so it arrives as numbers, and check any values that became missing."
            )
        elif action.action == "unify_labels":
            recs.append(
                f"'{action.column}' had labels differing only in case or spacing. "
                "Standardize them where the data is entered so counts don't split."
            )
        elif action.action in ("impute_median", "impute_mode"):
            recs.append(
                f"'{action.column}' had {action.rows_affected} missing value(s) filled during "
                "cleaning. Worth finding out why they were missing."
            )

    for issue in result.quality_issues:
        if issue.category == "outliers":
            recs.append(
                f"Review the {issue.details.get('outlier_count')} outlier(s) in '{issue.column}' "
                "before relying on its average."
            )
        elif issue.category == "constant":
            profile = next((v for v in result.variables if v.name == issue.column), None)
            if profile and profile.missing:
                recs.append(
                    f"'{issue.column}' has one value plus blanks: check whether a blank means 'no' "
                    "before treating it as missing."
                )
            else:
                recs.append(f"'{issue.column}' holds a single value, so it adds nothing to the analysis.")

    if not recs:
        recs.append("No data quality problems were found, so the figures can be read as they are.")
    return recs[:MAX_RECOMMENDATIONS]


# ---------------------------------------------------------------------------
# Model-written text, with every failure path landing on the rule-based text.
# ---------------------------------------------------------------------------


async def explain_analysis(result: AnalysisResult, client: LLMClient | None = None) -> Explanation:
    if not is_llm_configured():
        return rule_based_explanation(result, configured=False)

    client = client or make_client()
    facts = build_facts(result)
    try:
        reply = await client.chat_json(EXPLAIN_SYSTEM_PROMPT, json.dumps({"facts": facts}, default=str))
        parsed = ModelExplanation.model_validate(reply.data)
    except LLMError as exc:
        return _explanation_fallback(result, f"model call failed: {exc}")
    except ValidationError:
        return _explanation_fallback(result, "model reply was missing required fields")

    known_charts = {c.id for c in result.charts}
    chart_notes = [
        {"chart_id": n["chart_id"], "explanation": n["explanation"]}
        for n in parsed.chart_explanations
        if n.get("chart_id") in known_charts and n.get("explanation")
    ]

    written = [parsed.dataset_overview, parsed.analysis_summary, *parsed.recommendations]
    written += [n["explanation"] for n in chart_notes]
    invented = ungrounded_numbers(" ".join(written), facts)
    if invented:
        return _explanation_fallback(result, f"model wrote numbers not in the analysis: {', '.join(invented[:5])}")

    _log_call("explain", reply, outcome="ok")
    return Explanation(
        dataset_overview=parsed.dataset_overview,
        analysis_summary=parsed.analysis_summary,
        recommendations=parsed.recommendations,
        chart_explanations=chart_notes,
        configured=True,
        source="llm",
        model=reply.model,
    )


def _explanation_fallback(result: AnalysisResult, reason: str) -> Explanation:
    logger.warning("LLM explanation fell back to rule-based text: %s", reason)
    return rule_based_explanation(result, configured=True, fallback_reason=reason)


def _log_call(kind: str, reply, *, outcome: str) -> None:
    logger.info(
        "llm %s %s model=%s latency_ms=%s attempts=%s prompt_tokens=%s completion_tokens=%s",
        kind,
        outcome,
        reply.model,
        reply.latency_ms,
        reply.attempts,
        reply.prompt_tokens,
        reply.completion_tokens,
    )
