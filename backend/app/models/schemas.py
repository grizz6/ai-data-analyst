from typing import Any

from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    name: str
    dtype: str
    non_null_count: int
    null_count: int
    null_pct: float
    unique_count: int
    sample_values: list[Any] = Field(default_factory=list)


class QualityIssue(BaseModel):
    severity: str
    category: str
    column: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CleaningAction(BaseModel):
    action: str
    column: str | None = None
    description: str
    rows_affected: int | None = None


class NumericSummary(BaseModel):
    column: str
    count: int
    mean: float | None
    std: float | None
    min: float | None
    q25: float | None
    median: float | None
    q75: float | None
    max: float | None


class CategoricalSummary(BaseModel):
    column: str
    top_values: list[dict[str, Any]]


class CorrelationPair(BaseModel):
    column_a: str
    column_b: str
    correlation: float


class TrendInsight(BaseModel):
    column: str
    direction: str
    change_pct: float | None
    message: str


class RuleInsight(BaseModel):
    category: str
    title: str
    message: str
    severity: str = "info"


class ChartSpec(BaseModel):
    id: str
    title: str
    chart_type: str
    plotly_json: dict[str, Any]


class LlamaExplanation(BaseModel):
    dataset_overview: str
    chart_explanations: list[dict[str, str]]
    analysis_summary: str
    recommendations: list[str]
    configured: bool = False


class AnalysisResult(BaseModel):
    session_id: str
    filename: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    quality_issues: list[QualityIssue]
    cleaning_actions: list[CleaningAction]
    numeric_summaries: list[NumericSummary]
    categorical_summaries: list[CategoricalSummary]
    correlations: list[CorrelationPair]
    trends: list[TrendInsight]
    rule_insights: list[RuleInsight]
    charts: list[ChartSpec]
    llama: LlamaExplanation
    preview_rows: list[dict[str, Any]]
    cleaned_preview_rows: list[dict[str, Any]]


class QuestionRequest(BaseModel):
    question: str


class QuestionResponse(BaseModel):
    answer: str
    configured: bool = False


class AskContext(BaseModel):
    """Structured facts passed to Llama when API is configured."""

    filename: str
    shape: tuple[int, int]
    column_names: list[str]
    quality_issue_count: int
    top_insights: list[str]
    numeric_highlights: list[str]
    categorical_highlights: list[str]
