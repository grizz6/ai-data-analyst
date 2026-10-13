import { useEffect, useRef, useState } from "react";
import { getSession, uploadDataset } from "./api";
import AnalysisDashboard from "./components/AnalysisDashboard";
import RecentAnalyses from "./components/RecentAnalyses";
import UploadPanel from "./components/UploadPanel";
import { forgetAll, forgetAnalysis, loadRecent, rememberAnalysis, type RecentAnalysis } from "./recent";
import { setTheme, useTheme } from "./theme";
import type { AnalysisResult } from "./types";

// Past this, the server is stuck or gone; better to say so than spin forever.
const UPLOAD_TIMEOUT_MS = 10 * 60_000;

function ThemeToggle() {
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
      onClick={() => setTheme(next)}
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        {theme === "dark" ? (
          <>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          </>
        ) : (
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
        )}
      </svg>
    </button>
  );
}

function Elapsed() {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="elapsed">{seconds} s</span>;
}

export default function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  // Kept so another sheet of the same workbook can be analyzed without re-picking the file.
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentAnalysis[]>(loadRecent);
  const [notice, setNotice] = useState<string | null>(null);
  const upload = useRef<AbortController | null>(null);

  const show = (data: AnalysisResult) => {
    setResult(data);
    setRecent(
      rememberAnalysis({
        sessionId: data.session_id,
        filename: data.sheet_name ? `${data.filename} (${data.sheet_name})` : data.filename,
        rows: data.row_count,
        columns: data.column_count,
        openedAt: Date.now(),
      }),
    );
    window.scrollTo({ top: 0 });
  };

  const analyze = async (target: File, sheet?: string) => {
    upload.current?.abort();
    const controller = new AbortController();
    upload.current = controller;
    const timer = setTimeout(() => controller.abort("timeout"), UPLOAD_TIMEOUT_MS);
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const data = await uploadDataset(target, sheet, controller.signal);
      setFile(target);
      show(data);
    } catch (e) {
      if (controller.signal.aborted) {
        if (controller.signal.reason === "timeout") {
          setError("The analysis took too long and was stopped. Try again, or try a smaller file.");
        }
      } else if (e instanceof TypeError) {
        // fetch throws TypeError when the connection drops before an answer.
        setError("Lost the connection to the server. Check your internet and try again.");
      } else {
        setError(e instanceof Error ? e.message : "Upload failed");
      }
    } finally {
      clearTimeout(timer);
      if (upload.current === controller) {
        upload.current = null;
        setLoading(false);
      }
    }
  };

  const cancel = () => {
    upload.current?.abort();
    upload.current = null;
    setLoading(false);
  };

  const reopen = async (sessionId: string) => {
    setLoading(true);
    setError(null);
    try {
      setFile(null);
      show(await getSession(sessionId));
    } catch (e) {
      // Expired or gone: drop it from the list so it isn't offered again.
      setRecent(forgetAnalysis(sessionId));
      setError(e instanceof Error ? e.message : "Couldn't open that analysis");
    } finally {
      setLoading(false);
    }
  };

  const startOver = () => {
    setResult(null);
    setFile(null);
    setError(null);
    setNotice(null);
  };

  const deleted = () => {
    if (result) setRecent(forgetAnalysis(result.session_id));
    startOver();
    setNotice("The analysis was deleted from the server.");
  };

  return (
    <>
      <div className="topbar">
        <div className="topbar-inner">
          <span className="brand">
            <span className="brand-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <rect x="3" y="12" width="4" height="9" rx="1.5" />
                <rect x="10" y="7" width="4" height="14" rx="1.5" />
                <rect x="17" y="3" width="4" height="18" rx="1.5" />
              </svg>
            </span>
            AI Data Analyst
          </span>
          <div className="topbar-actions">
            {result && (
              <button type="button" className="btn secondary" onClick={startOver}>
                New analysis
              </button>
            )}
            <ThemeToggle />
          </div>
        </div>
      </div>

      <main className="app">
        {!result && (
          <>
            <header className="hero">
              <span className="eyebrow">Exploratory data analysis</span>
              <h1>
                Understand any spreadsheet <span className="gradient-text">in seconds</span>
              </h1>
              <p>
                Upload a CSV or Excel file. Get its quality, every column profiled, how the columns relate,
                and an honest read on what the data can and can't support.
              </p>
            </header>
            <div className="panel">
              <UploadPanel onUpload={(f) => analyze(f)} onReject={setError} loading={loading} />
              {notice && (
                <p className="notice" role="status">
                  {notice}
                </p>
              )}
              {error && (
                <p className="error-msg" role="alert">
                  {error}
                </p>
              )}
              {loading && (
                <div className="loading" role="status">
                  <span className="spinner" aria-hidden="true" />
                  <div>
                    <p className="loading-title">
                      Analyzing your file <Elapsed />
                    </p>
                    <p className="muted">
                      Checking quality, profiling every column and testing relationships. Large files, or a
                      server that was asleep, can take a few minutes.
                    </p>
                  </div>
                  <button type="button" className="btn secondary small-btn" onClick={cancel}>
                    Cancel
                  </button>
                </div>
              )}
            </div>
            <RecentAnalyses
              items={recent}
              disabled={loading}
              onOpen={reopen}
              onClear={() => setRecent(forgetAll())}
            />
            <p className="privacy-note">
              Your file is processed on this server. Its results are deleted at the latest an hour after you
              last open them, or right away with the Delete button, and are only reachable through your
              private link. If the server has a language-model key set, the computed results (column names,
              statistics and the most common values, not the raw file) are sent to that model to write the
              explanation.
            </p>
          </>
        )}

        {result && (
          <>
            {error && (
              <p className="error-msg" role="alert">
                {error}
              </p>
            )}
            <AnalysisDashboard
              key={result.session_id}
              result={result}
              loading={loading}
              onAnalyzeSheet={file ? (sheet) => analyze(file, sheet) : undefined}
              onDeleted={deleted}
            />
          </>
        )}
      </main>
    </>
  );
}
