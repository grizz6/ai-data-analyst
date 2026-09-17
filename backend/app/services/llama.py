"""
Explanation layer.

All numbers and charts come from Pandas/Plotly in other services. This layer
only turns those results into readable text. Without a model configured it
writes that text from rules, so the output is deterministic and every figure
in it is copied from the analysis result rather than produced here.

The model client (Meta Llama 4 Scout) is still a TODO below.
"""

from typing import Any

from app.config import settings
from app.models.schemas import AnalysisResult, AskContext, LlamaExplanation, QuestionResponse

HIGHLIGHT_CATEGORIES = ("correlation", "trend", "categorical")
MAX_RECOMMENDATIONS = 6


def is_llama_configured() -> bool:
    return settings.llm_configured


def build_ask_context(result: AnalysisResult) -> AskContext:
    numeric_highlights = [
        f"{s.column}: mean={s.mean}, max={s.max}" for s in result.numeric_summaries[:8]
    ]
    categorical_highlights = [
        f"{c.column}: top={c.top_values[0]['value'] if c.top_values else 'n/a'}"
        for c in result.categorical_summaries[:8]
    ]
    top_insights = [i.message for i in result.rule_insights[:12]]

    return AskContext(
        filename=result.filename,
        shape=(result.row_count, result.column_count),
        column_names=[c.name for c in result.columns],
        quality_issue_count=len(result.quality_issues),
        top_insights=top_insights,
        numeric_highlights=numeric_highlights,
        categorical_highlights=categorical_highlights,
    )


def rule_based_explanation(result: AnalysisResult, *, configured: bool = False) -> LlamaExplanation:
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


def rule_based_answer(result: AnalysisResult, *, configured: bool = False) -> QuestionResponse:
    highlights = "\n".join(f"- {i.message}" for i in result.rule_insights[:6])
    return QuestionResponse(
        answer=(
            "Free-form questions need an LLM API key on the server, and none is set. "
            "Here is what the analysis found:\n"
            f"{highlights or '- No insights were generated for this file.'}"
        ),
        configured=configured,
    )


async def explain_analysis(result: AnalysisResult) -> LlamaExplanation:
    configured = is_llama_configured()
    if not configured:
        return rule_based_explanation(result, configured=False)

    # TODO: Call Meta Llama 4 Scout API with structured context from
    # build_ask_context(result) plus chart metadata. Keep prompts focused on
    # explanation only, and never ask the model to compute statistics.
    return rule_based_explanation(result, configured=True)


async def answer_question(result: AnalysisResult, question: str) -> QuestionResponse:
    if not is_llama_configured():
        return rule_based_answer(result, configured=False)

    # TODO: grounded prompt: question + AskContext + optional chart summaries
    return rule_based_answer(result, configured=True)


def llama_payload_for_debug(result: AnalysisResult) -> dict[str, Any]:
    """Structured payload you can send to Llama once the client is wired."""
    return {
        "context": build_ask_context(result).model_dump(),
        "charts": [{"id": c.id, "title": c.title, "type": c.chart_type} for c in result.charts],
        "insights": [i.model_dump() for i in result.rule_insights],
    }
