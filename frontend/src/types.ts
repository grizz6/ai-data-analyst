/**
 * API types, generated from the backend's OpenAPI schema.
 *
 * Don't edit shapes here. Change the Pydantic models in
 * backend/app/models/schemas.py and run scripts/gen-api-types.sh;
 * CI fails if src/generated/api-schema.ts is out of date.
 */
import type { components } from "./generated/api-schema";

type Schemas = components["schemas"];

export type AnalysisResult = Schemas["AnalysisResult"];
export type CategoricalSummary = Schemas["CategoricalSummary"];
export type ChartSpec = Schemas["ChartSpec"];
export type CleaningAction = Schemas["CleaningAction"];
export type ColumnProfile = Schemas["ColumnProfile"];
export type CorrelationPair = Schemas["CorrelationPair"];
export type Explanation = Schemas["Explanation"];
export type NumericSummary = Schemas["NumericSummary"];
export type QualityIssue = Schemas["QualityIssue"];
export type QuestionResponse = Schemas["QuestionResponse"];
export type RuleInsight = Schemas["RuleInsight"];
export type TrendInsight = Schemas["TrendInsight"];

export type ExplanationSource = Explanation["source"];
