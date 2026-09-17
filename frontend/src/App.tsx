import { useState } from "react";
import { uploadDataset } from "./api";
import AnalysisDashboard from "./components/AnalysisDashboard";
import UploadPanel from "./components/UploadPanel";
import type { AnalysisResult } from "./types";

export default function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async (file: File) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await uploadDataset(file);
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
          <UploadPanel onUpload={handleUpload} loading={loading} />
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
                setError(null);
              }}
            >
              Upload another file
            </button>
          </div>
          <AnalysisDashboard result={result} />
        </>
      )}
    </div>
  );
}
