from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr


class ApiModel(BaseModel):
    """Base for everything the API returns.

    Fields with defaults are always present in responses, so the OpenAPI schema
    marks them required. That keeps the generated TypeScript types from calling
    them optional.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ColumnProfile(ApiModel):
    name: str
    dtype: str
    non_null_count: int
    null_count: int
    null_pct: float
    unique_count: int
    sample_values: list[Any] = Field(default_factory=list)
    is_identifier: bool = False


class QualityIssue(ApiModel):
    severity: str
    category: str
    column: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class CleaningAction(ApiModel):
    action: str
    column: str | None = None
    description: str
    rows_affected: int | None = None


class NumericSummary(ApiModel):
    column: str
    count: int
    mean: float | None
    std: float | None
    min: float | None
    q25: float | None
    median: float | None
    q75: float | None
    max: float | None


class CategoricalSummary(ApiModel):
    column: str
    top_values: list[dict[str, Any]]


class CorrelationPair(ApiModel):
    column_a: str
    column_b: str
    correlation: float
    n: int = 0  # rows where both columns have a value
    p_value: float | None = None  # two-sided, H0: no linear relationship


class TrendInsight(ApiModel):
    column: str
    direction: str
    change_pct: float | None
    message: str
    slope: float | None = None  # fitted least-squares slope, in value units per slope_unit
    slope_unit: str | None = None  # "day", "month" or "row"
    p_value: float | None = None  # two-sided, H0: slope is zero


class RuleInsight(ApiModel):
    category: str
    title: str
    message: str
    severity: str = "info"


class ChartSpec(ApiModel):
    id: str
    title: str
    chart_type: str
    plotly_json: dict[str, Any]


ExplanationSource = Literal["rule_based", "llm"]


class LlamaExplanation(ApiModel):
    dataset_overview: str
    chart_explanations: list[dict[str, str]]
    analysis_summary: str
    recommendations: list[str]
    # configured: an API key is set. source: what actually wrote this text, which is
    # "rule_based" whenever the model is unset, unreachable, or failed the grounding check.
    configured: bool = False
    source: ExplanationSource = "rule_based"
    model: str | None = None
    fallback_reason: str | None = None


class ModelExplanation(ApiModel):
    """The JSON shape the model is asked to return, validated before use."""

    dataset_overview: str = Field(min_length=1)
    analysis_summary: str = Field(min_length=1)
    recommendations: list[str] = Field(default_factory=list, max_length=6)
    chart_explanations: list[dict[str, str]] = Field(default_factory=list)


class ModelAnswer(ApiModel):
    answer: str = Field(min_length=1)


class AnalysisResult(ApiModel):
    session_id: str
    filename: str
    sheet_name: str | None = None
    available_sheets: list[str] = Field(default_factory=list)
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

    # The full cleaned dataset as CSV, kept with the session for download but
    # left out of the JSON response, which only carries a preview.
    _cleaned_csv: bytes | None = PrivateAttr(default=None)

    @property
    def cleaned_csv(self) -> bytes | None:
        return self._cleaned_csv


class QuestionRequest(ApiModel):
    question: str


class QuestionResponse(ApiModel):
    answer: str
    configured: bool = False
    source: ExplanationSource = "rule_based"
    fallback_reason: str | None = None
