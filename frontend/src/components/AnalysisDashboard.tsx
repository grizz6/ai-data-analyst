import { lazy, Suspense, useRef, useState, type KeyboardEvent } from "react";
import { cleanedCsvUrl, deleteSession, dictionaryUrl, printableReportUrl, reportDownloadUrl } from "../api";
import { formatNumber, formatP, friendlyType } from "../format";
import {
  overviewTakeaway,
  qualityTakeaway,
  relationshipsTakeaway,
  suggestionsTakeaway,
  timeSeriesTakeaway,
  variablesTakeaway,
} from "../takeaways";
import type { AnalysisResult, ChartSpec, RecommendationAction } from "../types";
// Plotly is most of the app's JavaScript. Loading it with the charts, not with
// the upload screen, keeps the first page light.
const ChartGrid = lazy(() => import("./ChartGrid"));
import DataTable from "./DataTable";
import Hint from "./Hint";
import BreakdownExplorer from "./BreakdownExplorer";
import QualityExtras from "./QualityExtras";
import StatisticsPanel from "./StatisticsPanel";
import SuggestionsPanel from "./SuggestionsPanel";
import Tile from "./Tile";
import { KIND_LABELS } from "./VariableCard";
import TimeSeriesPanel from "./TimeSeriesPanel";
import VariablesPanel from "./VariablesPanel";

const AXIS_KINDS: Record<string, string> = {
  dates: "date column",
  date_parts: "date parts",
  epoch: "Unix time",
  year: "year column",
  step_column: "step column",
  row_order: "row order",
};

type TabId = "overview" | "quality" | "variables" | "relationships" | "time" | "next" | "data";

function Charts({ charts, result }: { charts: ChartSpec[]; result?: AnalysisResult }) {
  if (charts.length === 0) return null;
  return (
    <Suspense fallback={<p className="muted">Loading charts…</p>}>
      <ChartGrid charts={charts} explanation={result?.explanation} />
    </Suspense>
  );
}

interface Props {
  result: AnalysisResult;
  loading?: boolean;
  onAnalyzeSheet?: (sheet: string) => void;
  onDeleted?: () => void;
}

export default function AnalysisDashboard({ result, loading = false, onAnalyzeSheet, onDeleted }: Props) {
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleDelete = async () => {
    if (!window.confirm("Delete this analysis from the server now? The report and downloads will stop working.")) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteSession(result.session_id);
      onDeleted?.();
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : "Couldn't delete this analysis");
      setDeleting(false);
    }
  };

  const [previewTab, setPreviewTab] = useState<"raw" | "cleaned">("cleaned");

  const visuals = result.visuals ?? {};
  const tabs: [TabId, string][] = [
    ["overview", "Overview"],
    ["quality", "Data quality"],
    ["variables", "Variables"],
    ["relationships", "Relationships"],
    ...(result.time_series.length > 0 ? [["time", "Over time"] as [TabId, string]] : []),
    ["next", "Next steps"],
    ["data", "Data"],
  ];
  const [tab, setTab] = useState<TabId>(() => {
    const fromHash = window.location.hash.slice(1);
    return (tabs.find(([id]) => id === fromHash)?.[0] ?? "overview") as TabId;
  });
  const tabButtons = useRef<Record<string, HTMLButtonElement | null>>({});

  const choose = (id: TabId) => {
    setTab(id);
    window.history.replaceState(null, "", `#${id}`);
  };
  const [variable, setVariable] = useState<string | null>(null);
  const handleAction = (action: RecommendationAction) => {
    if (action.column) setVariable(action.column);
    if (tabs.some(([id]) => id === action.tab)) choose(action.tab as TabId);
  };
  const onTabKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const index = tabs.findIndex(([id]) => id === tab);
    const next = tabs[(index + step + tabs.length) % tabs.length][0];
    choose(next);
    tabButtons.current[next]?.focus();
  };


  // The same column types as the Variables tab and the written summary.
  const kinds = result.variables.reduce<Record<string, number>>((acc, v) => {
    const kind = KIND_LABELS[v.kind];
    acc[kind] = (acc[kind] ?? 0) + 1;
    return acc;
  }, {});
  const totalCells = result.columns.reduce((sum, c) => sum + c.null_count + c.non_null_count, 0);
  const missingCells = result.columns.reduce((sum, c) => sum + c.null_count, 0);
  const missingPct = totalCells ? (missingCells / totalCells) * 100 : 0;
  const toCheck = result.quality_issues.filter((i) => i.severity === "error" || i.severity === "warning").length;
  const strongest = [...result.correlations].sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation))[0];
  const realPairs = result.correlations.filter((c) => c.p_value !== null && c.p_value < 0.05).length;
  const realGroups = result.statistics.group_differences.filter((g) => g.p_adjusted !== null && g.p_adjusted < 0.05).length;
  const realAssociations = result.statistics.categorical_associations.filter(
    (a) => a.p_adjusted !== null && a.p_adjusted < 0.05,
  ).length;
  const seasonal = result.time_series.filter((t) => (t.seasonal_strength ?? 0) >= 0.4).length;

  const panelProps = (id: TabId) => ({
    id: `tab-${id}`,
    role: "tabpanel",
    "aria-labelledby": `tab-button-${id}`,
    className: "panel tab-panel",
  });

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
              {result.sampled
                ? `Sample of ${result.row_count.toLocaleString()} of ${result.rows_in_file.toLocaleString()} rows`
                : `${result.row_count.toLocaleString()} rows`}{" "}
              · {result.column_count} columns
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
          <a className="btn secondary" href={dictionaryUrl(result.session_id)} download>
            Data dictionary
          </a>
          <a className="btn secondary" href={cleanedCsvUrl(result.session_id)} download>
            Cleaned CSV
          </a>
          <button type="button" className="btn danger" disabled={deleting} onClick={handleDelete}>
            {deleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>
      {deleteError && (
        <p className="error-msg" role="alert">
          {deleteError}
        </p>
      )}

      <div className="dash-tabs" role="tablist" aria-label="Analysis sections">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            ref={(el) => {
              tabButtons.current[id] = el;
            }}
            id={`tab-button-${id}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            aria-controls={`tab-${id}`}
            tabIndex={tab === id ? 0 : -1}
            className={tab === id ? "dash-tab active" : "dash-tab"}
            onClick={() => choose(id)}
            onKeyDown={onTabKey}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <section {...panelProps("overview")}>
          <p className="takeaway">{overviewTakeaway(result)}</p>
          <div className="stats">
            <Tile label="Rows" value={result.row_count.toLocaleString()} />
            <Tile label="Columns" value={String(result.column_count)} />
            {Object.entries(kinds).map(([kind, count]) => (
              <Tile key={kind} label={kind} value={String(count)} />
            ))}
            <Tile label="Quality issues" value={String(result.quality_issues.length)} tone={toCheck ? "attention" : "good"} />
          </div>
          <div className="story" aria-label="What this dataset tells you">
            <h3>What this dataset is</h3>
            <p>{result.explanation.dataset_overview}</p>
            <h3>What it tells you</h3>
            <p style={{ whiteSpace: "pre-wrap" }}>{result.explanation.analysis_summary}</p>
            {result.explanation.recommendations.length > 0 && (
              <>
                <h3>Check before using it</h3>
                <ul>
                  {result.explanation.recommendations.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </>
            )}
            <p className="source-note">
              {result.explanation.source === "llm"
                ? `Written by ${result.explanation.model} from the computed results; every number in it was checked.`
                : result.explanation.configured && result.explanation.fallback_reason
                  ? `Rule-based: the language model's text wasn't used (${result.explanation.fallback_reason}).`
                  : "Rule-based summary, built from the computed results."}
            </p>
          </div>
          <h3>At a glance</h3>
          <Charts charts={[...(visuals.overview ?? []), ...(visuals.explore ?? [])]} result={result} />
          {result.numeric_summaries.length > 0 && (
            <div className="scroll-table">
              <table className="data" aria-label="Numeric statistics">
                <thead>
                  <tr>
                    <th>Column</th>
                    <th className="num">Mean</th>
                    <th className="num">Median</th>
                    <th className="num">Std dev</th>
                    <th className="num">Min</th>
                    <th className="num">25%</th>
                    <th className="num">75%</th>
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
                      <td className="num">{formatNumber(s.q25)}</td>
                      <td className="num">{formatNumber(s.q75)}</td>
                      <td className="num">{formatNumber(s.max)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result.rule_insights.length > 0 && (
            <details className="summary-details">
              <summary>All findings</summary>
              <ul className="insight-list">
                {result.rule_insights.map((insight, i) => (
                  <li key={i}>
                    <strong>{insight.title}:</strong> {insight.message}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}

      {tab === "quality" && (
        <section {...panelProps("quality")}>
          <p className="takeaway">{qualityTakeaway(result)}</p>
          <div className="stats">
            <Tile label="Issues" value={String(result.quality_issues.length)} tone={toCheck ? "attention" : "good"} />
            <Tile label="To check" value={String(toCheck)} hint="Issues marked warning or error" />
            <Tile label="Missing cells" value={`${formatNumber(Math.round(missingPct * 100) / 100)}%`} />
            <Tile label="Cleaning steps" value={String(result.cleaning_actions.length)} />
          </div>
          <Charts charts={visuals.quality ?? []} />
          <QualityExtras duplicates={result.duplicates} missing={result.missing_dependencies} />
          <div className="grid-2">
            <div>
              <h3>Issues</h3>
              {result.quality_issues.length === 0 ? (
                <p className="empty-good">
                  <span aria-hidden="true">✓</span> No issues found.
                </p>
              ) : (
                <ul className="issue-list">
                  {result.quality_issues.map((issue, i) => (
                    <li key={i}>
                      <span className={`badge ${issue.severity}`}>{issue.severity}</span> {issue.message}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3>
                Cleaning <Hint text="Applied to the cleaned copy only; the statistics use your data as recorded." />
              </h3>
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
        </section>
      )}

      {tab === "variables" && (
        <section {...panelProps("variables")}>
          <p className="takeaway">{variablesTakeaway(result)}</p>
          <VariablesPanel variables={result.variables} selected={variable} onSelect={setVariable} />
        </section>
      )}

      {tab === "relationships" && (
        <section {...panelProps("relationships")}>
          <p className="takeaway">{relationshipsTakeaway(result)}</p>
          <div className="stats">
            <Tile
              label="Strongest r"
              value={strongest ? strongest.correlation.toFixed(2) : "–"}
              hint={strongest ? `${strongest.column_a} ↔ ${strongest.column_b}` : undefined}
            />
            <Tile label="Linked pairs" value={String(realPairs)} hint="Numeric pairs with a correlation unlikely to be chance (p < 0.05)" />
            <Tile label="Group gaps" value={String(realGroups)} hint="Numbers that differ between a category's groups (adjusted p < 0.05)" />
            <Tile label="Linked categories" value={String(realAssociations)} hint="Category pairs that go together (chi-square, adjusted p < 0.05)" />
          </div>
          <Charts charts={visuals.relationships ?? []} />
          <BreakdownExplorer breakdowns={result.breakdowns} crosstabs={result.crosstabs} />
          {result.correlations.length > 0 && (
            <>
              <h3>Correlations</h3>
              <ul className="insight-list" aria-label="Correlations">
                {result.correlations.map((c, i) => (
                  <li key={i}>
                    {c.column_a} ↔ {c.column_b}: <strong>{c.correlation}</strong>{" "}
                    <span className="muted">
                      (n = {c.n}, {formatP(c.p_value)})
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
          <h3>Statistical tests</h3>
          <StatisticsPanel tests={result.statistics} />
        </section>
      )}

      {tab === "time" && (
        <section {...panelProps("time")}>
          <p className="takeaway">{timeSeriesTakeaway(result)}</p>
          <div className="stats">
            <Tile label="Series" value={String(result.time_series.length)} />
            {result.time_axis && (
              <Tile label="Time from" value={AXIS_KINDS[result.time_axis.kind] ?? result.time_axis.kind} hint={result.time_axis.label} />
            )}
            <Tile label="Seasonal" value={String(seasonal)} hint="Series where a repeating pattern explains 40% or more of the variation" />
          </div>
          <TimeSeriesPanel series={result.time_series} />
        </section>
      )}

      {tab === "next" && (
        <section {...panelProps("next")}>
          <p className="takeaway">{suggestionsTakeaway(result)}</p>
          <SuggestionsPanel
            sessionId={result.session_id}
            review={result.review}
            recommendations={result.recommendations}
            onAction={handleAction}
          />
        </section>
      )}

      {tab === "data" && (
        <section {...panelProps("data")}>
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
          <DataTable title="" rows={previewTab === "raw" ? result.preview_rows : result.cleaned_preview_rows} />
          <h3>Column profiles</h3>
          <div className="scroll-table">
            <table className="data" aria-label="Column profiles">
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
        </section>
      )}
    </>
  );
}
