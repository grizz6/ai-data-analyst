import { useState } from "react";
import { askQuestion, reportDownloadUrl } from "../api";
import type { AnalysisResult } from "../types";
import ChartGrid from "./ChartGrid";
import DataTable from "./DataTable";

interface Props {
  result: AnalysisResult;
  loading?: boolean;
  onAnalyzeSheet?: (sheet: string) => void;
}

export default function AnalysisDashboard({ result, loading = false, onAnalyzeSheet }: Props) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<"raw" | "cleaned">("cleaned");

  const handleAsk = async () => {
    if (!question.trim()) return;
    setAsking(true);
    setAskError(null);
    try {
      const res = await askQuestion(result.session_id, question);
      setAnswer(res.answer);
    } catch (e) {
      setAskError(e instanceof Error ? e.message : "Failed to get answer");
    } finally {
      setAsking(false);
    }
  };

  return (
    <>
      <div className="banner">
        <strong>Session:</strong> {result.session_id.slice(0, 8)}… ·{" "}
        <strong>File:</strong> {result.filename}
        {result.sheet_name && (
          <>
            {" "}· <strong>Sheet:</strong>{" "}
            {result.available_sheets.length > 1 && onAnalyzeSheet ? (
              <select
                className="sheet-select"
                value={result.sheet_name}
                disabled={loading}
                onChange={(e) => onAnalyzeSheet(e.target.value)}
              >
                {result.available_sheets.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            ) : (
              result.sheet_name
            )}
          </>
        )}
        {!result.llama.configured && (
          <> · Summaries are rule-based because no LLM API key is set on the server.</>
        )}
      </div>

      <div className="stats">
        <div className="stat">
          <div className="label">Rows</div>
          <div className="value">{result.row_count.toLocaleString()}</div>
        </div>
        <div className="stat">
          <div className="label">Columns</div>
          <div className="value">{result.column_count}</div>
        </div>
        <div className="stat">
          <div className="label">Quality issues</div>
          <div className="value">{result.quality_issues.length}</div>
        </div>
        <div className="stat">
          <div className="label">Charts</div>
          <div className="value">{result.charts.length}</div>
        </div>
        <div className="stat">
          <div className="label">Insights</div>
          <div className="value">{result.rule_insights.length}</div>
        </div>
      </div>

      <div style={{ margin: "1rem 0" }}>
        <a
          className="btn"
          href={reportDownloadUrl(result.session_id)}
          download
        >
          Download HTML report
        </a>
      </div>

      <div className="panel">
        <h2>Summary {result.llama.configured ? "(LLM)" : "(rule-based)"}</h2>
        <p>{result.llama.dataset_overview}</p>
        <h3 style={{ fontSize: "0.95rem", marginTop: "1rem" }}>Analysis summary</h3>
        <p style={{ whiteSpace: "pre-wrap" }}>{result.llama.analysis_summary}</p>
        {result.llama.recommendations.length > 0 && (
          <>
            <h3 style={{ fontSize: "0.95rem", marginTop: "1rem" }}>Recommendations</h3>
            <ul>
              {result.llama.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="grid-2">
        <div className="panel">
          <h2>Data quality</h2>
          {result.quality_issues.length === 0 ? (
            <p style={{ color: "var(--muted)" }}>No issues detected.</p>
          ) : (
            <ul className="issue-list">
              {result.quality_issues.map((issue, i) => (
                <li key={i}>
                  <span className={`badge ${issue.severity}`}>{issue.severity}</span>{" "}
                  {issue.message}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="panel">
          <h2>Cleaning actions</h2>
          {result.cleaning_actions.length === 0 ? (
            <p style={{ color: "var(--muted)" }}>No cleaning was needed.</p>
          ) : (
            <ul className="insight-list">
              {result.cleaning_actions.map((a, i) => (
                <li key={i}>{a.description}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="panel">
        <h2>Key insights</h2>
        <ul className="insight-list">
          {result.rule_insights.map((insight, i) => (
            <li key={i}>
              <strong>{insight.title}:</strong> {insight.message}
            </li>
          ))}
        </ul>
      </div>

      {result.numeric_summaries.length > 0 && (
        <div className="panel">
          <h2>Numeric statistics</h2>
          <div className="scroll-table">
            <table className="data">
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Mean</th>
                  <th>Median</th>
                  <th>Std</th>
                  <th>Min</th>
                  <th>Max</th>
                </tr>
              </thead>
              <tbody>
                {result.numeric_summaries.map((s) => (
                  <tr key={s.column}>
                    <td>{s.column}</td>
                    <td>{s.mean?.toLocaleString()}</td>
                    <td>{s.median?.toLocaleString()}</td>
                    <td>{s.std?.toLocaleString()}</td>
                    <td>{s.min?.toLocaleString()}</td>
                    <td>{s.max?.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {result.correlations.length > 0 && (
        <div className="panel">
          <h2>Correlations</h2>
          <ul className="insight-list">
            {result.correlations.map((c, i) => (
              <li key={i}>
                {c.column_a} ↔ {c.column_b}: <strong>{c.correlation}</strong>
              </li>
            ))}
          </ul>
        </div>
      )}

      {result.trends.length > 0 && (
        <div className="panel">
          <h2>Trends</h2>
          <ul className="insight-list">
            {result.trends.map((t, i) => (
              <li key={i}>{t.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="panel">
        <h2>Visualizations</h2>
        <ChartGrid charts={result.charts} llama={result.llama} />
      </div>

      <div className="panel">
        <h2>Ask a question</h2>
        <p style={{ color: "var(--muted)", fontSize: "0.9rem", marginTop: 0 }}>
          Questions are answered from the pre-computed analysis facts. Free-form answers
          need an LLM API key on the server; without one you get the key findings.
        </p>
        <div className="qa-box">
          <textarea
            placeholder="e.g. Which region had the highest sales? What trends do you see?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <div style={{ marginTop: "0.75rem" }}>
            <button
              type="button"
              className="btn"
              disabled={asking || !question.trim()}
              onClick={handleAsk}
            >
              {asking ? "Thinking…" : "Ask"}
            </button>
          </div>
          {askError && <p className="error-msg">{askError}</p>}
          {answer && <div className="qa-answer">{answer}</div>}
        </div>
      </div>

      <div className="panel">
        <div className="tabs">
          <button
            type="button"
            className={`tab ${previewTab === "raw" ? "active" : ""}`}
            onClick={() => setPreviewTab("raw")}
          >
            Raw preview
          </button>
          <button
            type="button"
            className={`tab ${previewTab === "cleaned" ? "active" : ""}`}
            onClick={() => setPreviewTab("cleaned")}
          >
            Cleaned preview
          </button>
        </div>
        <DataTable
          title=""
          rows={previewTab === "raw" ? result.preview_rows : result.cleaned_preview_rows}
        />
      </div>

      <div className="panel">
        <h2>Column profiles</h2>
        <div className="scroll-table">
          <table className="data">
            <thead>
              <tr>
                <th>Column</th>
                <th>Type</th>
                <th>Missing %</th>
                <th>Unique</th>
                <th>Samples</th>
              </tr>
            </thead>
            <tbody>
              {result.columns.map((col) => (
                <tr key={col.name}>
                  <td>{col.name}</td>
                  <td>
                    {col.dtype}
                    {col.is_identifier && <span className="badge info">identifier</span>}
                  </td>
                  <td>{col.null_pct}%</td>
                  <td>{col.unique_count}</td>
                  <td>{col.sample_values.slice(0, 3).join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
