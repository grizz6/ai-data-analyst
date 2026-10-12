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


class Explanation(ApiModel):
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


class CustomChartRequest(ApiModel):
    """A chart the user builds: which kind, and which columns go where.

    histogram: x (numeric). bar: x (category), plus y when aggregating a value.
    scatter: x and y (both numeric). line: x (date or number), plus y when
    aggregating a value. box: y (numeric), optionally split by x (category).
    """

    chart_type: Literal["histogram", "bar", "scatter", "line", "box"]
    x: str | None = Field(default=None, max_length=500)
    y: str | None = Field(default=None, max_length=500)
    aggregate: Literal["count", "sum", "mean", "median"] = "count"


class DistributionStat(ApiModel):
    column: str
    n: int
    skewness: float | None
    # Excess kurtosis: 0 for a normal distribution, above 0 for heavier tails.
    kurtosis: float | None
    # D'Agostino-Pearson test, H0: the values come from a normal distribution.
    normality_p: float | None
    shape: str
    # Values more than 3 standard deviations from the mean.
    zscore_outliers: int


class RankCorrelation(ApiModel):
    column_a: str
    column_b: str
    n: int
    pearson: float | None
    spearman: float
    kendall: float | None  # computed on up to 5,000 rows
    p_value: float | None  # for Spearman's rho
    p_adjusted: float | None  # Benjamini-Hochberg across every pair tested


class CategoricalAssociation(ApiModel):
    column_a: str
    column_b: str
    n: int
    chi_square: float
    dof: int
    p_value: float
    p_adjusted: float | None
    cramers_v: float
    # More than 20% of expected counts under 5, where the chi-square p-value is unreliable.
    sparse: bool


class GroupDifference(ApiModel):
    group_column: str
    value_column: str
    groups: int
    n: int
    anova_f: float | None
    anova_p: float | None
    kruskal_h: float | None
    kruskal_p: float | None
    p_adjusted: float | None  # Benjamini-Hochberg on the Kruskal-Wallis p-values
    # Share of the value's variance explained by the groups (0 to 1).
    eta_squared: float
    highest_group: str
    highest_mean: float
    lowest_group: str
    lowest_mean: float


class MissingPattern(ApiModel):
    column_a: str
    column_b: str
    both_missing: int
    # Correlation between the two columns' "is missing" indicators.
    correlation: float


class StatisticalTests(ApiModel):
    distributions: list[DistributionStat] = Field(default_factory=list)
    rank_correlations: list[RankCorrelation] = Field(default_factory=list)
    categorical_associations: list[CategoricalAssociation] = Field(default_factory=list)
    group_differences: list[GroupDifference] = Field(default_factory=list)
    missing_patterns: list[MissingPattern] = Field(default_factory=list)


class TimeAxisInfo(ApiModel):
    # "dates", "date_parts", "epoch", "year", "step_column" or "row_order"
    kind: str
    columns: list[str]
    label: str


class ForecastPoint(ApiModel):
    date: str
    value: float
    lower: float
    upper: float


class TimeSeriesAnalysis(ApiModel):
    column: str
    date_column: str
    # How the values were grouped in time ("daily", "weekly", "monthly", ...) and averaged.
    frequency: str
    points: int
    # Periods with no data, filled by straight-line interpolation for these tests only.
    filled_gaps: int
    rolling_window: int
    # Augmented Dickey-Fuller test, H0: the series has a unit root (is not stationary).
    adf_statistic: float | None
    adf_p: float | None
    stationary: bool | None
    # The lag (in periods) with the strongest autocorrelation beyond chance, if any.
    strongest_lag: int | None
    strongest_lag_acf: float | None
    seasonal_period: int | None
    # 0 to 1: how much of the variation the repeating seasonal pattern accounts for.
    seasonal_strength: float | None
    trend_strength: float | None
    forecast_method: str
    forecast: list[ForecastPoint] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    summary: str


class ClusterProfile(ApiModel):
    cluster: int
    size: int
    # Columns where this group sits furthest from the overall average, in standard deviations.
    distinctive: list[dict[str, Any]] = Field(default_factory=list)


class ClusterAnalysis(ApiModel):
    features: list[str]
    rows_used: int
    k: int
    # -1 to 1; above about 0.5 is clear separation, under 0.25 is no real structure.
    silhouette: float
    clear: bool
    clusters: list[ClusterProfile] = Field(default_factory=list)
    # Share of the variation each principal component captures.
    pca_explained: list[float] = Field(default_factory=list)
    # Silhouette score for each number of groups tried, starting at 2.
    k_scores: list[float] = Field(default_factory=list)
    # Each group's average of every feature, in standard deviations from the overall average.
    centers: list[list[float]] = Field(default_factory=list)
    chart: ChartSpec | None = None
    summary: str


class ModelRequest(ApiModel):
    target: str = Field(max_length=500)


class ModelScore(ApiModel):
    name: str
    # "baseline", "linear", "neighbours", "bayes", "tree", "bagging", "boosting" or "kernel"
    family: str
    # The task's main metric (accuracy, or R²): mean and spread over cross-validation
    # folds of the training rows, then on the training rows themselves and on the held-out test rows.
    cv_mean: float
    cv_std: float
    train_score: float
    test_score: float
    # Macro F1 for classification, mean absolute error for regression, on the test rows.
    test_secondary: float
    # Area under the ROC curve on the test rows, for classification when the model gives scores.
    test_auc: float | None = None
    fit_seconds: float
    # Train score more than 0.1 above test score.
    overfit: bool


class FeatureImportance(ApiModel):
    feature: str
    # Drop in the test score when this column is shuffled (permutation importance).
    importance: float
    spread: float


class TargetSuggestion(ApiModel):
    column: str
    task: Literal["classification", "regression"]
    reason: str


class ModelReport(ApiModel):
    target: str
    task: Literal["classification", "regression"]
    primary_metric: str
    secondary_metric: str
    rows_used: int
    train_rows: int
    test_rows: int
    features: list[str]
    dropped_features: list[str] = Field(default_factory=list)
    folds: int
    scores: list[ModelScore]
    # Chosen by cross-validation score, never by the test rows.
    best_model: str
    beats_baseline: bool
    # Further test-set measures for the best model (e.g. precision, recall, RMSE).
    best_test_metrics: dict[str, float] = Field(default_factory=dict)
    importances: list[FeatureImportance] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    summary: str


class ChatTurn(ApiModel):
    """One question asked about an analysis, and the answer it got."""

    question: str
    answer: str
    source: ExplanationSource = "rule_based"
    model: str | None = None
    fallback_reason: str | None = None


VariableKind = Literal["binary", "number", "count", "category", "date", "identifier", "text", "constant"]


class BoxStats(ApiModel):
    """Five-number summary; low and high are the whisker ends (the furthest values inside 1.5 x IQR)."""

    n: int
    q1: float
    median: float
    q3: float
    low: float
    high: float
    mean: float


class OutlierRow(ApiModel):
    row: int
    value: float
    z: float | None = None
    rules: list[str] = Field(default_factory=list)
    cause: str
    label: str | None = None


class OutlierCorrelation(ApiModel):
    column: str
    r_all: float
    r_without: float


class OutlierSummary(ApiModel):
    iqr_low: float
    iqr_high: float
    iqr_count: int
    iqr_share: float
    z_threshold: float = 3.0
    z_count: int
    z_share: float
    mean_all: float
    mean_without: float
    median_all: float
    median_without: float
    std_all: float
    std_without: float
    correlation: OutlierCorrelation | None = None
    rows: list[OutlierRow] = Field(default_factory=list)


class Histogram(ApiModel):
    edges: list[float]
    counts: list[int]


class Curve(ApiModel):
    x: list[Any]
    y: list[float]


class CategoryCount(ApiModel):
    value: str
    count: int
    share: float


class BinaryInfo(ApiModel):
    values: list[str]
    counts: list[int]
    positive: str
    positive_share: float


class GroupBox(ApiModel):
    label: str
    box: BoxStats


class BinarySplit(ApiModel):
    """One numeric variable for the rows on each side of a binary column."""

    binary_column: str
    groups: list[GroupBox]
    p_value: float | None = None
    effect: float | None = None


class BinaryComparison(ApiModel):
    """How much one variable differs between a binary column's two groups."""

    column: str
    kind: str
    effect: float
    effect_name: str
    p_value: float | None = None
    detail: str


class VariableProfile(ApiModel):
    name: str
    kind: VariableKind
    count: int
    missing: int
    missing_share: float
    distinct: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    skewness: float | None = None
    box: BoxStats | None = None
    # Charts zoom to this range when far-out values (beyond 3 x IQR) would squash them.
    view: list[float] | None = None
    beyond_view: int = 0
    histogram: Histogram | None = None
    density: Curve | None = None
    qq: Curve | None = None
    timeline: Curve | None = None
    timeline_label: str | None = None
    categories: list[CategoryCount] = Field(default_factory=list)
    binary: BinaryInfo | None = None
    outliers: OutlierSummary | None = None
    splits: list[BinarySplit] = Field(default_factory=list)
    compared: list[BinaryComparison] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class RecommendationAction(ApiModel):
    tab: str
    target: str | None = None
    column: str | None = None
    label: str


class Recommendation(ApiModel):
    id: str
    analysis: str
    title: str
    why: str
    columns: list[str] = Field(default_factory=list)
    action: RecommendationAction
    score: float = 0.0


class PlanRequest(ApiModel):
    goal: str = Field(max_length=1_000)


class PlanStep(ApiModel):
    id: str
    title: str
    why: str
    action: RecommendationAction


class PlanResponse(ApiModel):
    goal: str
    steps: list[PlanStep]
    note: str | None = None
    configured: bool = False
    source: ExplanationSource = "rule_based"
    model: str | None = None
    fallback_reason: str | None = None


class ModelPlan(ApiModel):
    """What the language model must return for a goal: steps chosen from the offered analyses."""

    class Step(ApiModel):
        id: str
        why: str = Field(min_length=1)

    steps: list[Step] = Field(min_length=1)
    note: str | None = None


class AnalysisResult(ApiModel):
    session_id: str
    filename: str
    sheet_name: str | None = None
    available_sheets: list[str] = Field(default_factory=list)
    row_count: int
    column_count: int
    # Rows in the uploaded file. Larger than the rows analyzed when a big file was
    # analyzed on a random sample (sampled is then true); every figure describes the sample.
    rows_in_file: int = 0
    sampled: bool = False
    columns: list[ColumnProfile]
    quality_issues: list[QualityIssue]
    cleaning_actions: list[CleaningAction]
    numeric_summaries: list[NumericSummary]
    categorical_summaries: list[CategoricalSummary]
    correlations: list[CorrelationPair]
    trends: list[TrendInsight]
    rule_insights: list[RuleInsight]
    charts: list[ChartSpec]
    explanation: Explanation
    statistics: StatisticalTests = Field(default_factory=StatisticalTests)
    time_axis: TimeAxisInfo | None = None
    time_series: list[TimeSeriesAnalysis] = Field(default_factory=list)
    clustering: ClusterAnalysis | None = None
    # Charts for each dashboard tab ("overview", "quality", "explore", "relationships", "clustering").
    visuals: dict[str, list[ChartSpec]] = Field(default_factory=dict)
    variables: list[VariableProfile] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    # Columns worth predicting, most likely first; the Models tab trains the first one.
    model_targets: list[TargetSuggestion] = Field(default_factory=list)
    preview_rows: list[dict[str, Any]]
    cleaned_preview_rows: list[dict[str, Any]]
    # Questions asked so far, oldest first. Kept with the session, so the thread
    # survives a reload and earlier answers give follow-up questions context.
    chat_history: list[ChatTurn] = Field(default_factory=list)

    # The full cleaned dataset as CSV, kept with the session for download but
    # left out of the JSON response, which only carries a preview.
    _cleaned_csv: bytes | None = PrivateAttr(default=None)
    # The prepared data (no filled-in values, no identifier columns) that custom charts are drawn from.
    _chart_csv: bytes | None = PrivateAttr(default=None)

    @property
    def cleaned_csv(self) -> bytes | None:
        return self._cleaned_csv

    @property
    def chart_csv(self) -> bytes | None:
        return self._chart_csv


class QuestionRequest(ApiModel):
    question: str = Field(max_length=2_000)


class QuestionResponse(ApiModel):
    answer: str
    configured: bool = False
    source: ExplanationSource = "rule_based"
    model: str | None = None
    fallback_reason: str | None = None
