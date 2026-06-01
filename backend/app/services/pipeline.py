import uuid

from app.models.schemas import AnalysisResult, LlamaExplanation
from app.services import analysis, charts, cleaning, ingestion, insights, llama, profiling, quality
from app.services.ingestion import df_preview_records


async def run_full_analysis(file_bytes: bytes, filename: str) -> AnalysisResult:
    raw_df = ingestion.load_dataframe(file_bytes, filename)
    quality_issues = quality.check_quality(raw_df)
    cleaned_df, cleaning_actions = cleaning.clean_dataframe(raw_df)

    columns = profiling.profile_columns(cleaned_df)
    numeric_summaries = analysis.numeric_summaries(cleaned_df)
    categorical_summaries = analysis.categorical_summaries(cleaned_df)
    correlations = analysis.top_correlations(cleaned_df)
    trends = analysis.detect_trends(cleaned_df)
    chart_specs = charts.build_charts(cleaned_df)
    rule_insights = insights.generate_rule_insights(
        cleaned_df,
        quality_issues,
        numeric_summaries,
        categorical_summaries,
        correlations,
        trends,
    )

    session_id = str(uuid.uuid4())
    placeholder_llama = LlamaExplanation(
        dataset_overview="",
        chart_explanations=[],
        analysis_summary="",
        recommendations=[],
        configured=False,
    )

    result = AnalysisResult(
        session_id=session_id,
        filename=filename,
        row_count=len(cleaned_df),
        column_count=len(cleaned_df.columns),
        columns=columns,
        quality_issues=quality_issues,
        cleaning_actions=cleaning_actions,
        numeric_summaries=numeric_summaries,
        categorical_summaries=categorical_summaries,
        correlations=correlations,
        trends=trends,
        rule_insights=rule_insights,
        charts=chart_specs,
        llama=placeholder_llama,
        preview_rows=df_preview_records(raw_df),
        cleaned_preview_rows=df_preview_records(cleaned_df),
    )

    explanation = await llama.explain_analysis(result)
    return result.model_copy(update={"llama": explanation})
