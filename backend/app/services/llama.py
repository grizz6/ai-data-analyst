"""
Meta Llama 4 Scout integration (stub).

When you have an API key, set:
  ADA_LLAMA_API_KEY=<your-key>
  ADA_LLAMA_API_BASE=<optional endpoint URL>

Llama is used only for natural-language tasks. All numbers and charts
come from Pandas/Plotly in other services.
"""

import os
from typing import Any

from app.models.schemas import (
    AnalysisResult,
    AskContext,
    ChartSpec,
    LlamaExplanation,
    QuestionResponse,
    RuleInsight,
)


def is_llama_configured() -> bool:
    return bool(os.getenv("ADA_LLAMA_API_KEY", "").strip())


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


def _placeholder_explanation(
    result: AnalysisResult, *, configured: bool = False
) -> LlamaExplanation:
    chart_notes = [
        {
            "chart_id": c.id,
            "explanation": (
                f"[Llama placeholder] Chart '{c.title}' ({c.chart_type}) — "
                "connect ADA_LLAMA_API_KEY to get a natural-language explanation."
            ),
        }
        for c in result.charts
    ]

    insight_lines = "\n".join(f"- {i.message}" for i in result.rule_insights[:8])

    return LlamaExplanation(
        dataset_overview=(
            f"[Llama placeholder] Your file '{result.filename}' has "
            f"{result.row_count:,} rows and {result.column_count} columns. "
            "Statistical results below were computed with Pandas."
        ),
        chart_explanations=chart_notes,
        analysis_summary=(
            "[Llama placeholder] Rule-based insights from the analysis pipeline:\n"
            f"{insight_lines or '- No insights generated.'}"
        ),
        recommendations=[
            "[Llama placeholder] Review columns with high missingness.",
            "[Llama placeholder] Validate outliers before acting on them.",
            "Set ADA_LLAMA_API_KEY to enable AI-generated recommendations.",
        ],
        configured=configured,
    )


async def explain_analysis(result: AnalysisResult) -> LlamaExplanation:
    configured = is_llama_configured()
    if not configured:
        return _placeholder_explanation(result, configured=False)

    # TODO: Call Meta Llama 4 Scout API with structured context from
    # build_ask_context(result) plus chart metadata. Keep prompts focused on
    # explanation only — do not ask the model to compute statistics.
    return _placeholder_explanation(result, configured=True)


async def answer_question(result: AnalysisResult, question: str) -> QuestionResponse:
    if not is_llama_configured():
        context = build_ask_context(result)
        return QuestionResponse(
            answer=(
                "[Llama placeholder] Llama is not configured yet. "
                f"Your question was: \"{question}\"\n\n"
                "Facts available to the model once connected:\n"
                f"- File: {context.filename}, shape {context.shape}\n"
                f"- Columns: {', '.join(context.column_names[:15])}"
                f"{'...' if len(context.column_names) > 15 else ''}\n"
                f"- Sample insights:\n"
                + "\n".join(f"  • {m}" for m in context.top_insights[:5])
                + "\n\nSet ADA_LLAMA_API_KEY to get natural-language answers."
            ),
            configured=False,
        )

    # TODO: RAG-style prompt: question + AskContext + optional chart summaries
    return QuestionResponse(
        answer="[Llama] API key present but client not implemented yet.",
        configured=True,
    )


def llama_payload_for_debug(result: AnalysisResult) -> dict[str, Any]:
    """Structured payload you can send to Llama once the client is wired."""
    return {
        "context": build_ask_context(result).model_dump(),
        "charts": [{"id": c.id, "title": c.title, "type": c.chart_type} for c in result.charts],
        "insights": [i.model_dump() for i in result.rule_insights],
    }
