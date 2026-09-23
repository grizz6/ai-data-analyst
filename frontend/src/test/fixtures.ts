import type { AnalysisResult } from "../types";
import sample from "./fixtures/analysis-result.json";

/**
 * A real /api/upload response for sample-data/sales_sample.csv, with chart
 * payloads emptied to keep it small. Each call returns a fresh copy.
 */
export function sampleResult(overrides: Partial<AnalysisResult> = {}): AnalysisResult {
  return { ...structuredClone(sample as AnalysisResult), ...overrides };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
