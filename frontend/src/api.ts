import type { AnalysisResult, QuestionResponse } from "./types";

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

export function reportDownloadUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/report`;
}

export function cleanedCsvUrl(sessionId: string): string {
  return `/api/sessions/${sessionId}/cleaned.csv`;
}
