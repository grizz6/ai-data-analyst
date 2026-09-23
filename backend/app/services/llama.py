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
    LlamaExplanation,
    ModelAnswer,
    ModelExplanation,
    QuestionResponse,
)
from app.services.grounding import ungrounded_numbers
from app.services.llm_client import LLMClient, LLMError

logger = logging.getLogger(__name__)

HIGHLIGHT_CATEGORIES = ("correlation", "trend", "categorical")
MAX_RECOMMENDATIONS = 6
MAX_QUESTION_CHARS = 1_000

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
You explain the results of an automated data analysis. The numbers were computed by code;
your job is only to explain what they mean.

{GROUND_RULES}

The JSON object must have exactly these keys:
- "dataset_overview": 2 to 3 sentences on what the file contains and its data quality.
- "analysis_summary": 3 to 5 sentences on the most important findings.
- "recommendations": a list of up to 5 short, practical next steps.
- "chart_explanations": a list of objects with "chart_id" (copied from the facts) and
  "explanation" (one or two sentences on what that chart shows)."""

ANSWER_SYSTEM_PROMPT = f"""\
You answer a question about a dataset using only the results of an automated analysis.

{GROUND_RULES}

The JSON object must have exactly one key, "answer", holding your answer as a string."""


def is_llama_configured() -> bool:
    return settings.llm_configured


def make_client() -> LLMClient:
    return LLMClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )


def build_facts(result: AnalysisResult) -> dict[str, Any]:
    """Everything the model may talk about. It is not allowed to go beyond this."""
    return {
        "file": {
            "name": result.filename,
            "sheet": result.sheet_name,
            "rows_after_cleaning": result.row_count,
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
            {"severity": q.severity, "category": q.category, "message": q.message}
            for q in result.quality_issues
        ],
        "cleaning_actions": [a.description for a in result.cleaning_actions],
        "numeric_summaries": [s.model_dump() for s in result.numeric_summaries],
        "top_categories": [
            {"column": c.column, "top_values": c.top_values[:5]} for c in result.categorical_summaries
        ],
        "correlations": [p.model_dump() for p in result.correlations],
        "trends": [t.model_dump() for t in result.trends],
        "findings": [i.message for i in result.rule_insights],
        "charts": [{"chart_id": c.id, "title": c.title, "type": c.chart_type} for c in result.charts],
    }


# ---------------------------------------------------------------------------
# Rule-based text: used when no model is configured, and as the fallback.
# ---------------------------------------------------------------------------


def rule_based_explanation(
    result: AnalysisResult, *, configured: bool = False, fallback_reason: str | None = None
) -> LlamaExplanation:
    issue_count = len(result.quality_issues)
    overview = (
        f"'{result.filename}' has {result.row_count:,} rows and {result.column_count} columns "
        f"after cleaning. {issue_count} data quality issue{'s' if issue_count != 1 else ''} "
        "were flagged before cleaning. Every figure in this analysis was computed with Pandas."
    )

    highlights = [i.message for i in result.rule_insights if i.category in HIGHLIGHT_CATEGORIES]
    summary = (
        " ".join(highlights[:4])
        if highlights
        else "No strong correlations, trends, or dominant categories stood out in this file."
    )

    return LlamaExplanation(
        dataset_overview=overview,
        chart_explanations=[],
        analysis_summary=summary,
        recommendations=_recommendations(result),
        configured=configured,
        source="rule_based",
        fallback_reason=fallback_reason,
    )


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
            recs.append(f"'{issue.column}' holds a single value, so it adds nothing to the analysis.")

    if not recs:
        recs.append("No data quality problems were found, so the figures can be read as they are.")
    return recs[:MAX_RECOMMENDATIONS]


def rule_based_answer(
    result: AnalysisResult, *, configured: bool = False, fallback_reason: str | None = None
) -> QuestionResponse:
    # Titles carry the column name ("Summary for sales"); some messages don't repeat it.
    highlights = "\n".join(f"- {i.title}: {i.message}" for i in result.rule_insights[:6])
    opening = (
        "The language model couldn't answer just now, so here is what the analysis found:"
        if configured
        else "Free-form questions need an LLM API key on the server, and none is set. "
        "Here is what the analysis found:"
    )
    return QuestionResponse(
        answer=f"{opening}\n{highlights or '- No insights were generated for this file.'}",
        configured=configured,
        source="rule_based",
        fallback_reason=fallback_reason,
    )


# ---------------------------------------------------------------------------
# Model-written text, with every failure path landing on the rule-based text.
# ---------------------------------------------------------------------------


async def explain_analysis(result: AnalysisResult, client: LLMClient | None = None) -> LlamaExplanation:
    if not is_llama_configured():
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
    return LlamaExplanation(
        dataset_overview=parsed.dataset_overview,
        analysis_summary=parsed.analysis_summary,
        recommendations=parsed.recommendations,
        chart_explanations=chart_notes,
        configured=True,
        source="llm",
        model=reply.model,
    )


async def answer_question(
    result: AnalysisResult, question: str, client: LLMClient | None = None
) -> QuestionResponse:
    if not is_llama_configured():
        return rule_based_answer(result, configured=False)

    client = client or make_client()
    facts = build_facts(result)
    user_message = json.dumps({"question": question[:MAX_QUESTION_CHARS], "facts": facts}, default=str)
    try:
        reply = await client.chat_json(ANSWER_SYSTEM_PROMPT, user_message)
        parsed = ModelAnswer.model_validate(reply.data)
    except LLMError as exc:
        return _answer_fallback(result, f"model call failed: {exc}")
    except ValidationError:
        return _answer_fallback(result, "model reply was missing the answer")

    # The question itself may contain numbers ("top 3"), so those count as given too.
    invented = ungrounded_numbers(parsed.answer, {"facts": facts, "question": question})
    if invented:
        return _answer_fallback(result, f"model wrote numbers not in the analysis: {', '.join(invented[:5])}")

    _log_call("answer", reply, outcome="ok")
    return QuestionResponse(answer=parsed.answer, configured=True, source="llm")


def _explanation_fallback(result: AnalysisResult, reason: str) -> LlamaExplanation:
    logger.warning("LLM explanation fell back to rule-based text: %s", reason)
    return rule_based_explanation(result, configured=True, fallback_reason=reason)


def _answer_fallback(result: AnalysisResult, reason: str) -> QuestionResponse:
    logger.warning("LLM answer fell back to rule-based text: %s", reason)
    return rule_based_answer(result, configured=True, fallback_reason=reason)


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
