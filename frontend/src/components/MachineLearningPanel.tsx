import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { trainModel } from "../api";
import { formatNumber } from "../format";
import type { ClusterAnalysis, ColumnProfile, Explanation, ModelReport, TargetSuggestion } from "../types";

const ChartGrid = lazy(() => import("./ChartGrid"));

const NO_NOTES: Explanation = {
  dataset_overview: "",
  analysis_summary: "",
  recommendations: [],
  chart_explanations: [],
  configured: false,
  source: "rule_based",
  model: null,
  fallback_reason: null,
};

interface Props {
  sessionId: string;
  columns: ColumnProfile[];
  clustering: ClusterAnalysis | null;
  suggestions: TargetSuggestion[];
  /** Train the first suggested target as soon as the panel appears. */
  autoTrain?: boolean;
}

export default function MachineLearningPanel({ sessionId, columns, clustering, suggestions, autoTrain = false }: Props) {
  const suggested = suggestions.map((t) => t.column);
  const others = columns
    .filter((c) => !c.is_identifier && !c.dtype.startsWith("datetime") && !suggested.includes(c.name))
    .map((c) => c.name);
  const targets = [...suggested, ...others];
  const [target, setTarget] = useState(autoTrain ? (suggested[0] ?? "") : "");
  const [report, setReport] = useState<ModelReport | null>(null);
  const [training, setTraining] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleTrain = async (column: string = target) => {
    setTraining(true);
    setError(null);
    try {
      setReport(await trainModel(sessionId, column));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Prediction failed");
    } finally {
      setTraining(false);
    }
  };

  const started = useRef(false);
  useEffect(() => {
    if (autoTrain && suggested[0] && !started.current) {
      started.current = true;
      void handleTrain(suggested[0]);
    }
    // Runs once per analysis; the panel is re-mounted for a new one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <section className="stats-section">
        <h3>Groups of similar rows</h3>
        {clustering ? (
          <>
            <p>{clustering.summary}</p>
            <p className="panel-lead">
              K-means on {clustering.features.length} numeric columns ({clustering.rows_used.toLocaleString()} rows),
              with the number of groups picked by silhouette score (−1 to 1; under 0.25 means no real grouping).
            </p>
            {clustering.clear && (
              <div className="scroll-table">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Group</th>
                      <th className="num">Rows</th>
                      <th>Stands out for</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clustering.clusters.map((c) => (
                      <tr key={c.cluster}>
                        <td>Group {c.cluster}</td>
                        <td className="num">{c.size.toLocaleString()}</td>
                        <td>
                          {c.distinctive
                            .map((d) => {
                              const sd = Number(d.sd_from_average);
                              return `${d.column} ${sd > 0 ? "high" : "low"} (avg ${formatNumber(Number(d.mean))}, ${sd > 0 ? "+" : ""}${sd.toFixed(1)} SD)`;
                            })
                            .join(" · ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {clustering.chart && (
              <Suspense fallback={<p className="muted">Loading chart…</p>}>
                <ChartGrid charts={[clustering.chart]} explanation={NO_NOTES} />
              </Suspense>
            )}
          </>
        ) : (
          <p className="muted">Grouping needs at least two numeric columns and 50 rows.</p>
        )}
      </section>

      <section className="stats-section">
        <h3>Predict a column</h3>
        <p className="panel-lead">
          Pick a column to predict from the others. A baseline, k-nearest neighbours, a linear model and a random forest
          are compared with cross-validation, so the scores reflect rows each model didn't see.
        </p>
        <div className="builder-form">
          <label className="builder-field" htmlFor="ml-target">
            <span>Column to predict</span>
            <select
              id="ml-target"
              className="builder-select"
              value={target}
              onChange={(e) => {
                setTarget(e.target.value);
                setReport(null);
              }}
            >
              <option value="">Choose…</option>
              {targets.map((name) => (
                <option key={name} value={name}>
                  {suggested.includes(name) ? `${name} (suggested)` : name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn" disabled={!target || training} onClick={() => handleTrain()}>
            {training ? "Training models…" : "Train and compare"}
          </button>
        </div>
        {training && (
          <p className="muted small" role="status">
            Training {report ? "" : "11 models "}on {target}… up to a few minutes on large files.
          </p>
        )}
        {error && (
          <p className="error-msg" role="alert">
            {error}
          </p>
        )}
        {report && <ModelResults report={report} />}
      </section>
    </>
  );
}

function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function ModelResults({ report }: { report: ModelReport }) {
  const classification = report.task === "classification";
  const show = (value: number) => (classification ? pct(value) : value.toFixed(3));
  const best = report.scores.find((s) => s.name === report.best_model)!;
  const ranked = [...report.scores].sort((a, b) => b.cv_mean - a.cv_mean);
  return (
    <div className="model-results" aria-label="Model results">
      <p className="takeaway">{report.summary}</p>
      <div className="stats">
        <div className="stat">
          <div className="label">Best model</div>
          <div className="value small-value">{report.best_model}</div>
        </div>
        <div className="stat">
          <div className="label">Test {report.primary_metric}</div>
          <div className="value">{show(best.test_score)}</div>
        </div>
        <div className="stat">
          <div className="label">CV {report.primary_metric}</div>
          <div className="value">
            {show(best.cv_mean)} <span className="muted small">±{show(best.cv_std)}</span>
          </div>
        </div>
        {Object.entries(report.best_test_metrics)
          .filter(([name]) => name !== report.primary_metric && name !== "accuracy")
          .slice(0, 3)
          .map(([name, value]) => (
            <div className="stat" key={name}>
              <div className="label">{name}</div>
              <div className="value">{formatNumber(value)}</div>
            </div>
          ))}
        <div className="stat">
          <div className="label">Train / test rows</div>
          <div className="value">
            {report.train_rows.toLocaleString()} / {report.test_rows.toLocaleString()}
          </div>
        </div>
      </div>

      <div className="scroll-table">
        <table className="data">
          <thead>
            <tr>
              <th>Model</th>
              <th>Type</th>
              <th className="num" title={`${report.folds}-fold cross-validation on the training rows`}>
                CV {report.primary_metric}
              </th>
              <th className="num">Train</th>
              <th className="num">Test</th>
              <th className="num">Test {report.secondary_metric}</th>
              {classification && <th className="num">Test AUC</th>}
              <th className="num">Seconds</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {ranked.map((s) => (
              <tr key={s.name} className={s.name === report.best_model ? "best" : undefined}>
                <td>{s.name}</td>
                <td className="muted">{s.family}</td>
                <td className="num">
                  {show(s.cv_mean)} <span className="muted">±{show(s.cv_std)}</span>
                </td>
                <td className="num">{show(s.train_score)}</td>
                <td className="num">{show(s.test_score)}</td>
                <td className="num">{formatNumber(s.test_secondary)}</td>
                {classification && <td className="num">{s.test_auc === null ? "–" : s.test_auc.toFixed(3)}</td>}
                <td className="num">{s.fit_seconds.toFixed(1)}</td>
                <td>
                  {s.name === report.best_model && <span className="badge good">best</span>}
                  {s.overfit && (
                    <span className="badge warning" title="Train score more than 0.1 above test score">
                      overfits
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Suspense fallback={<p className="muted">Loading charts…</p>}>
        <ChartGrid charts={report.charts} explanation={NO_NOTES} />
      </Suspense>
      {report.notes.length > 0 && <p className="muted small">{report.notes.join(" ")}</p>}
    </div>
  );
}
