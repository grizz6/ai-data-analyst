import { useState } from "react";
import { uploadDataset } from "./api";
import AnalysisDashboard from "./components/AnalysisDashboard";
import UploadPanel from "./components/UploadPanel";
import type { AnalysisResult } from "./types";

export default function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  // Kept so another sheet of the same workbook can be analyzed without re-picking the file.
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = async (target: File, sheet?: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await uploadDataset(target, sheet);
      setFile(target);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header>
        <h1>AI Data Analyst Agent</h1>
        <p>
          Upload a dataset and get automated quality checks, cleaning, statistics,
          charts, and insights. Every number is computed with Pandas; an optional
          language model only explains the results.
        </p>
      </header>

      {!result && (
        <div className="panel">
          <h2>Upload dataset</h2>
          <UploadPanel onUpload={(f) => analyze(f)} onReject={setError} loading={loading} />
          {error && <p className="error-msg">{error}</p>}
          {loading && <p className="loading">Running analysis pipeline…</p>}
        </div>
      )}

      {result && (
        <>
          <div style={{ marginBottom: "1rem" }}>
            <button
              type="button"
              className="btn secondary"
              onClick={() => {
                setResult(null);
                setFile(null);
                setError(null);
              }}
            >
              Upload another file
            </button>
          </div>
          {error && <p className="error-msg">{error}</p>}
          <AnalysisDashboard
            key={result.session_id}
            result={result}
            loading={loading}
            onAnalyzeSheet={file ? (sheet) => analyze(file, sheet) : undefined}
          />
        </>
      )}
    </div>
  );
}
