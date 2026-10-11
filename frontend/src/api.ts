import type { AnalysisResult, ChartSpec, CustomChartRequest, QuestionResponse } from "./types";

export async function uploadDataset(file: File, sheet?: string): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("file", file);

  const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : "";
  const res = await fetch(`/api/upload${query}`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Upload failed");
  }
  return res.json();
}

export async function askQuestion(
  sessionId: string,
  question: string
): Promise<QuestionResponse> {
  const res = await fetch(`/api/sessions/${sessionId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Question failed");
  }
  return res.json();
}

export async function buildChart(sessionId: string, request: CustomChartRequest): Promise<ChartSpec> {
  const res = await fetch(`/api/sessions/${sessionId}/charts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof err.detail === "string" ? err.detail : "Chart failed");
  }
  return res.json();
}

export function sampleDataUrl(): string {
  return "/api/sample.csv";
}

export function reportDownloadUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/report`;
}

/** The report as a print-ready page that opens the browser's print dialog, to save as PDF. */
export function printableReportUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/report?print=true`;
}

export function cleanedCsvUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/cleaned.csv`;
}
