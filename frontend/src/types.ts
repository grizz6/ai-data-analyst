export interface ColumnProfile {
  name: string;
  dtype: string;
  non_null_count: number;
  null_count: number;
  null_pct: number;
  unique_count: number;
  sample_values: unknown[];
  is_identifier: boolean;
}

export interface QualityIssue {
  severity: string;
  category: string;
  column?: string | null;
  message: string;
}

export interface CleaningAction {
  action: string;
  column?: string | null;
  description: string;
  rows_affected?: number | null;
}

export interface NumericSummary {
  column: string;
  count: number;
  mean: number | null;
  std: number | null;
  min: number | null;
  median: number | null;
  max: number | null;
}

export interface CategoricalSummary {
  column: string;
  top_values: { value: string; count: number }[];
}

export interface CorrelationPair {
  column_a: string;
  column_b: string;
  correlation: number;
}

export interface TrendInsight {
  column: string;
  direction: string;
  change_pct: number | null;
  message: string;
}

export interface RuleInsight {
  category: string;
  title: string;
  message: string;
  severity?: string;
}

export interface ChartSpec {
  id: string;
  title: string;
  chart_type: string;
  plotly_json: Record<string, unknown>;
}

export type ExplanationSource = "rule_based" | "llm";

export interface LlamaExplanation {
  dataset_overview: string;
  chart_explanations: { chart_id: string; explanation: string }[];
  analysis_summary: string;
  recommendations: string[];
  /** An API key is set on the server. */
  configured: boolean;
  /** What actually wrote the text; rule_based when the model is unset or its reply was rejected. */
  source: ExplanationSource;
  model: string | null;
  fallback_reason: string | null;
}

export interface AnalysisResult {
  session_id: string;
  filename: string;
  sheet_name: string | null;
  available_sheets: string[];
  row_count: number;
  column_count: number;
  columns: ColumnProfile[];
  quality_issues: QualityIssue[];
  cleaning_actions: CleaningAction[];
  numeric_summaries: NumericSummary[];
  categorical_summaries: CategoricalSummary[];
  correlations: CorrelationPair[];
  trends: TrendInsight[];
  rule_insights: RuleInsight[];
  charts: ChartSpec[];
  llama: LlamaExplanation;
  preview_rows: Record<string, unknown>[];
  cleaned_preview_rows: Record<string, unknown>[];
}

export interface QuestionResponse {
  answer: string;
  configured: boolean;
  source: ExplanationSource;
  fallback_reason: string | null;
}
