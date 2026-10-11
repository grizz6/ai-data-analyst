import { useState } from "react";
import { getSession, uploadDataset } from "./api";
import AnalysisDashboard from "./components/AnalysisDashboard";
import RecentAnalyses from "./components/RecentAnalyses";
import UploadPanel from "./components/UploadPanel";
import { forgetAnalysis, loadRecent, rememberAnalysis, type RecentAnalysis } from "./recent";
import type { AnalysisResult } from "./types";

export default function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  // Kept so another sheet of the same workbook can be analyzed without re-picking the file.
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentAnalysis[]>(loadRecent);

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
    setLoading(true);
    setError(null);
    try {
      const data = await uploadDataset(target, sheet);
      setFile(target);
      show(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setLoading(false);
    }
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
  };

  return (
    <>
      <div className="topbar">
        <div className="topbar-inner">
          <span className="brand">
            <span className="brand-mark" aria-hidden="true">
              ▦
            </span>
            AI Data Analyst
          </span>
          {result && (
            <button type="button" className="btn secondary" onClick={startOver}>
              New analysis
            </button>
          )}
        </div>
      </div>

      <main className="app">
        {!result && (
          <>
            <header className="hero">
              <h1>Understand a spreadsheet in seconds</h1>
              <p>
                Upload a CSV or Excel file to get quality checks, cleaning, statistics, charts and
                plain-English insights. Every number is computed with Pandas; an optional language
                model only explains the results.
              </p>
            </header>
            <div className="panel">
              <UploadPanel onUpload={(f) => analyze(f)} onReject={setError} loading={loading} />
              {error && (
                <p className="error-msg" role="alert">
                  {error}
                </p>
              )}
              {loading && (
                <div className="loading" role="status">
                  <span className="spinner" aria-hidden="true" />
                  <p>Analyzing your file: checking quality, cleaning, computing statistics and drawing charts…</p>
                  <p className="muted">Large files can take up to a minute.</p>
                </div>
              )}
            </div>
            <RecentAnalyses items={recent} disabled={loading} onOpen={reopen} />
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
            />
          </>
        )}
      </main>
    </>
  );
}
