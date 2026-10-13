import type { AnalysisResult, PlanResponse } from "./types";

/** The server's message for a failed request, or `fallback` when it sent none worth showing. */
async function errorMessage(res: Response, fallback: string): Promise<string> {
  const body = await res.json().catch(() => null);
  // Our own errors carry a sentence; validation errors (422) carry a list meant for developers.
  return typeof body?.detail === "string" ? body.detail : fallback;
}

export async function uploadDataset(file: File, sheet?: string): Promise<AnalysisResult> {
  const form = new FormData();
  form.append("file", file);

  const query = sheet ? `?sheet=${encodeURIComponent(sheet)}` : "";
  const res = await fetch(`/api/upload${query}`, { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await errorMessage(res, "Upload failed"));
  }
  return res.json();
}

/** A stored analysis, for reopening it. Throws with the server's message if it has expired. */
export async function getSession(sessionId: string): Promise<AnalysisResult> {
  const res = await fetch(`/api/sessions/${sessionId}`);
  if (!res.ok) {
    throw new Error(await errorMessage(res, "Couldn't open that analysis"));
  }
  return res.json();
}

/** Order the analyses that fit this file into a plan for a business goal. */
export async function planForGoal(sessionId: string, goal: string): Promise<PlanResponse> {
  const res = await fetch(`/api/sessions/${sessionId}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "Couldn't make a plan"));
  return res.json();
}

/** Remove an analysis from the server now. An already-gone one counts as deleted. */
export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) {
    throw new Error(await errorMessage(res, "Couldn't delete this analysis"));
  }
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

export function dictionaryUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/dictionary.csv`;
}

export function cleanedCsvUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/cleaned.csv`;
}
