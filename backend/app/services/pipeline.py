import uuid

from starlette.concurrency import run_in_threadpool

from app.models.schemas import AnalysisResult, LlamaExplanation, RuleInsight
from app.services import (
    analysis,
    charts,
    cleaning,
    ingestion,
    insights,
    llama,
    profiling,
    quality,
    semantics,
)
from app.services.ingestion import df_preview_records


async def run_full_analysis(
    file_bytes: bytes, filename: str, sheet: str | None = None
) -> AnalysisResult:
    # Pandas work is CPU-bound and would block every other request if run on
    # the event loop, so it runs in a worker thread. Only the explanation
    # step, which waits on network I/O, runs on the loop.
    result = await run_in_threadpool(compute_analysis, file_bytes, filename, sheet)
    explanation = await llama.explain_analysis(result)
    return result.model_copy(update={"llama": explanation})


def compute_analysis(file_bytes: bytes, filename: str, sheet: str | None = None) -> AnalysisResult:
    """Every number in the result is computed here, synchronously."""
    table = ingestion.load_table(file_bytes, filename, sheet)
    raw_df = table.df
    identifiers = semantics.identifier_columns(raw_df)
    quality_issues = quality.check_quality(raw_df, identifiers=identifiers)

    # prepared_df has duplicates and empty columns removed and dates parsed, but no
    # filled-in values: every statistic below comes from recorded data only.
    prepared_df, prepare_actions = cleaning.prepare_dataframe(raw_df, identifiers=identifiers)
    cleaned_df, fill_actions = cleaning.fill_missing(prepared_df, identifiers=identifiers)
    cleaning_actions = prepare_actions + fill_actions

    # Statistics and charts only see columns that measure something.
    metrics_df = prepared_df.drop(columns=[c for c in identifiers if c in prepared_df.columns])

    columns = profiling.profile_columns(prepared_df, identifiers=identifiers)
    numeric_summaries = analysis.numeric_summaries(metrics_df)
    categorical_summaries = analysis.categorical_summaries(metrics_df)
    correlations = analysis.top_correlations(metrics_df)
    trends = analysis.detect_trends(metrics_df)
    chart_specs = charts.build_charts(metrics_df)
    rule_insights = insights.generate_rule_insights(
        prepared_df,
        quality_issues,
        numeric_summaries,
        categorical_summaries,
        correlations,
        trends,
        identifiers=identifiers,
    )
    other_sheets = [s for s in table.available_sheets if s != table.sheet]
    if other_sheets:
        rule_insights.insert(
            1,
            RuleInsight(
                category="overview",
                title="Workbook sheets",
                message=(
                    f"Analyzed sheet '{table.sheet}'. The workbook also has "
                    f"{', '.join(repr(s) for s in other_sheets)}, which can be analyzed separately."
                ),
            ),
        )

    empty_explanation = LlamaExplanation(
        dataset_overview="",
        chart_explanations=[],
        analysis_summary="",
        recommendations=[],
        configured=False,
    )

    result = AnalysisResult(
        session_id=str(uuid.uuid4()),
        filename=filename,
        sheet_name=table.sheet,
        available_sheets=table.available_sheets,
        row_count=len(prepared_df),
        column_count=len(prepared_df.columns),
        columns=columns,
        quality_issues=quality_issues,
        cleaning_actions=cleaning_actions,
        numeric_summaries=numeric_summaries,
        categorical_summaries=categorical_summaries,
        correlations=correlations,
        trends=trends,
        rule_insights=rule_insights,
        charts=chart_specs,
        llama=empty_explanation,
        preview_rows=df_preview_records(raw_df),
        cleaned_preview_rows=df_preview_records(cleaned_df),
    )
    # utf-8-sig adds the byte-order mark Excel needs to show accented text correctly.
    result._cleaned_csv = cleaned_df.to_csv(index=False).encode("utf-8-sig")
    return result
