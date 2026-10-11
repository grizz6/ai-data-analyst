import { lazy, Suspense, useState } from "react";
import { askQuestion, cleanedCsvUrl, printableReportUrl, reportDownloadUrl } from "../api";
import { formatNumber, formatP, friendlyType } from "../format";
import type { AnalysisResult, ChatTurn } from "../types";
// Plotly is most of the app's JavaScript. Loading it with the charts, not with
// the upload screen, keeps the first page light.
const ChartGrid = lazy(() => import("./ChartGrid"));
import ChartBuilder from "./ChartBuilder";
import DataTable from "./DataTable";

/** A few questions this file can answer, built from its own columns. */
export function suggestedQuestions(result: AnalysisResult): string[] {
  const questions: string[] = [];
  const category = result.categorical_summaries[0]?.column;
  const measure = result.numeric_summaries[0]?.column;
  if (category && measure) questions.push(`Which ${category} has the highest ${measure}?`);
  const pair = result.correlations[0];
  if (pair) questions.push(`How are ${pair.column_a} and ${pair.column_b} related?`);
  const trend = result.trends[0];
  if (trend) questions.push(`How is ${trend.column} changing over time?`);
  questions.push("What should I look into first?");
  return questions;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  if (!navigator.clipboard) return null;
  return (
    <button
      type="button"
      className="link-btn small"
      onClick={() =>
        navigator.clipboard.writeText(text).then(
          () => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          },
          () => {},
        )
      }
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

interface Props {
  result: AnalysisResult;
  loading?: boolean;
  onAnalyzeSheet?: (sheet: string) => void;
}

export default function AnalysisDashboard({ result, loading = false, onAnalyzeSheet }: Props) {
  const [question, setQuestion] = useState("");
  // Starts from the thread stored with the session, so it survives a reload.
  const [thread, setThread] = useState<ChatTurn[]>(result.chat_history);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [previewTab, setPreviewTab] = useState<"raw" | "cleaned">("cleaned");

  const handleAsk = async (text: string = question) => {
    const asked = text.trim();
    if (!asked || asking) return;
    setAsking(true);
    setAskError(null);
    try {
      const res = await askQuestion(result.session_id, asked);
      setThread((turns) => [
        ...turns,
        {
          question: asked,
          answer: res.answer,
          source: res.source,
          model: res.model,
          fallback_reason: res.fallback_reason,
        },
      ]);
      setQuestion("");
    } catch (e) {
      setAskError(e instanceof Error ? e.message : "Failed to get answer");
    } finally {
      setAsking(false);
    }
  };

  const asked = new Set(thread.map((t) => t.question));
  const suggestions = suggestedQuestions(result).filter((q) => !asked.has(q));
  const sections: [string, string][] = [
    ["summary", "Summary"],
    ["quality", "Quality"],
    ["insights", "Insights"],
    ...(result.numeric_summaries.length > 0 ? [["statistics", "Statistics"] as [string, string]] : []),
    ["charts", "Charts"],
    ["chart-builder", "Build a chart"],
    ["ask", "Ask"],
    ["data", "Data"],
    ["columns", "Columns"],
  ];

  return (
    <>
      <div className="file-card">
        <div className="file-main">
          <span className="file-icon" aria-hidden="true">
            ▤
          </span>
          <div>
            <h1 className="file-name">{result.filename}</h1>
            <p className="muted small">
              {result.row_count.toLocaleString()} rows · {result.column_count} columns
              {result.sheet_name && (
                <>
                  {" "}· Sheet{" "}
                  {result.available_sheets.length > 1 && onAnalyzeSheet ? (
                    <select
                      className="sheet-select"
                      aria-label="Sheet"
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
            </p>
          </div>
        </div>
        <div className="actions">
          <a className="btn" href={reportDownloadUrl(result.session_id)} download>
            Download report
          </a>
          <a
            className="btn secondary"
            href={printableReportUrl(result.session_id)}
            target="_blank"
            rel="noopener noreferrer"
            title="Opens the report in a new tab with the print dialog; choose 'Save as PDF'."
          >
            Save as PDF
          </a>
          <a className="btn secondary" href={cleanedCsvUrl(result.session_id)} download>
            Cleaned CSV
          </a>
        </div>
      </div>

      <div className="stats">
        <div className={`stat ${result.quality_issues.length > 0 ? "attention" : "good"}`}>
          <div className="label">Quality issues</div>
          <div className="value">{result.quality_issues.length}</div>
        </div>
        <div className="stat">
          <div className="label">Cleaning steps</div>
          <div className="value">{result.cleaning_actions.length}</div>
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

      <nav className="section-nav" aria-label="Jump to section">
        {sections.map(([id, label]) => (
          <a
            key={id}
            href={`#${id}`}
            onClick={() => {
              // Jumping to a collapsed section opens it.
              const target = document.getElementById(id);
              if (target instanceof HTMLDetailsElement) target.open = true;
            }}
          >
            {label}
          </a>
        ))}
      </nav>

      <div id="summary" className="panel">
        <h2>Summary</h2>
        <p className="source-note">
          {result.explanation.source === "llm"
            ? `Written by ${result.explanation.model} from the computed results; every number in it was checked.`
            : result.explanation.configured && result.explanation.fallback_reason
              ? `Rule-based: the language model's text wasn't used (${result.explanation.fallback_reason}).`
              : "Rule-based summary. Set an LLM API key on the server for a written explanation."}
        </p>
        <p>{result.explanation.dataset_overview}</p>
        <h3>Key findings</h3>
        <p style={{ whiteSpace: "pre-wrap" }}>{result.explanation.analysis_summary}</p>
        {result.explanation.recommendations.length > 0 && (
          <>
            <h3>Recommendations</h3>
            <ul>
              {result.explanation.recommendations.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div id="quality" className="grid-2">
        <div className="panel">
          <h2>Data quality</h2>
          {result.quality_issues.length === 0 ? (
            <p className="empty-good">
              <span aria-hidden="true">✓</span> No issues found.
            </p>
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
            <p className="empty-good">
              <span aria-hidden="true">✓</span> No cleaning was needed.
            </p>
          ) : (
            <ul className="insight-list">
              {result.cleaning_actions.map((a, i) => (
                <li key={i}>{a.description}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div id="insights" className="panel">
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
        <div id="statistics" className="panel">
          <h2>Numeric statistics</h2>
          <div className="scroll-table">
            <table className="data">
              <thead>
                <tr>
                  <th>Column</th>
                  <th className="num">Mean</th>
                  <th className="num">Median</th>
                  <th className="num">Std dev</th>
                  <th className="num">Min</th>
                  <th className="num">Max</th>
                </tr>
              </thead>
              <tbody>
                {result.numeric_summaries.map((s) => (
                  <tr key={s.column}>
                    <td>{s.column}</td>
                    <td className="num">{formatNumber(s.mean)}</td>
                    <td className="num">{formatNumber(s.median)}</td>
                    <td className="num">{formatNumber(s.std)}</td>
                    <td className="num">{formatNumber(s.min)}</td>
                    <td className="num">{formatNumber(s.max)}</td>
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
                {c.column_a} ↔ {c.column_b}: <strong>{c.correlation}</strong>{" "}
                <span className="muted">
                  (n = {c.n}, {formatP(c.p_value)})
                </span>
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

      <div id="charts" className="panel">
        <h2>Visualizations</h2>
        <Suspense fallback={<p className="muted">Loading charts…</p>}>
          <ChartGrid charts={result.charts} explanation={result.explanation} />
        </Suspense>
      </div>

      <div id="chart-builder" className="panel">
        <h2>Build your own chart</h2>
        <p className="panel-lead">
          Pick a chart type and columns. The server computes every figure from your data as
          recorded, without the filled-in gaps.
        </p>
        <ChartBuilder sessionId={result.session_id} columns={result.columns} />
      </div>

      <div id="ask" className="panel">
        <h2>Ask a question</h2>
        <p className="panel-lead">
          Answers come from the computed results only. Free-form answers need an LLM API key on
          the server; without one you get the key findings. Follow-ups can refer to earlier answers.
        </p>
        {thread.length > 0 && (
          <ol className="qa-thread" aria-label="Questions and answers">
            {thread.map((turn, i) => (
              <li key={i}>
                <div className="qa-question">{turn.question}</div>
                <div className="qa-answer">
                  {turn.answer}
                  <div className="qa-meta">
                    <span className="qa-source">
                      {turn.source === "llm" ? `Written by ${turn.model}` : "Rule-based"}
                    </span>
                    <CopyButton text={turn.answer} />
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
        {suggestions.length > 0 && (
          <div className="suggestions" aria-label="Suggested questions">
            {suggestions.map((q) => (
              <button key={q} type="button" className="chip" disabled={asking} onClick={() => handleAsk(q)}>
                {q}
              </button>
            ))}
          </div>
        )}
        <div className="qa-box">
          <textarea
            aria-label="Your question"
            placeholder={
              thread.length > 0
                ? "Ask a follow-up…"
                : "e.g. Which region had the highest sales? What trends do you see?"
            }
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void handleAsk();
              }
            }}
          />
          <div className="qa-actions">
            <span className="muted small">Enter to send · Shift+Enter for a new line</span>
            <button
              type="button"
              className="btn"
              disabled={asking || !question.trim()}
              onClick={() => handleAsk()}
            >
              {asking ? "Thinking…" : "Ask"}
            </button>
          </div>
          {askError && <p className="error-msg">{askError}</p>}
        </div>
      </div>

      <details id="data" className="panel collapsible">
        <summary>
          <h2>Data preview</h2>
        </summary>
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
      </details>

      <details id="columns" className="panel collapsible">
        <summary>
          <h2>Column profiles</h2>
        </summary>
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
                  <td title={col.dtype}>
                    {friendlyType(col.dtype)}
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
      </details>
    </>
  );
}
