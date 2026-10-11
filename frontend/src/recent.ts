/**
 * Analyses this browser opened recently, so one can be reopened without
 * uploading the file again. Only the session ID and a label are kept; the
 * results themselves stay on the server and expire there as usual.
 *
 * Storage can be unavailable (private windows, blocked site data), so every
 * access is wrapped and the app works the same without it.
 */
export interface RecentAnalysis {
  sessionId: string;
  filename: string;
  rows: number;
  columns: number;
  openedAt: number;
}

const KEY = "ada.recent-analyses";
const MAX_RECENT = 5;

export function loadRecent(): RecentAnalysis[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? (parsed as RecentAnalysis[]).filter((r) => typeof r?.sessionId === "string") : [];
  } catch {
    return [];
  }
}

function save(list: RecentAnalysis[]): RecentAnalysis[] {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    // Not stored this time; the list is a convenience only.
  }
  return list;
}

export function rememberAnalysis(entry: RecentAnalysis): RecentAnalysis[] {
  const rest = loadRecent().filter((r) => r.sessionId !== entry.sessionId);
  return save([entry, ...rest].slice(0, MAX_RECENT));
}

export function forgetAll(): RecentAnalysis[] {
  return save([]);
}

export function forgetAnalysis(sessionId: string): RecentAnalysis[] {
  return save(loadRecent().filter((r) => r.sessionId !== sessionId));
}
