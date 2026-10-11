import { lazy, Suspense, useState } from "react";
import { trainModel } from "../api";
import { formatNumber } from "../format";
import type { ClusterAnalysis, ColumnProfile, Explanation, ModelReport } from "../types";

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
}

export default function MachineLearningPanel({ sessionId, columns, clustering }: Props) {
  const targets = columns.filter((c) => !c.is_identifier && !c.dtype.startsWith("datetime")).map((c) => c.name);
  const [target, setTarget] = useState("");
  const [report, setReport] = useState<ModelReport | null>(null);
  const [training, setTraining] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleTrain = async () => {
    setTraining(true);
    setError(null);
    try {
      setReport(await trainModel(sessionId, target));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Prediction failed");
    } finally {
      setTraining(false);
    }
  };

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
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn" disabled={!target || training} onClick={handleTrain}>
            {training ? "Training models…" : "Train and compare"}
          </button>
        </div>
        {training && <p className="muted small">This can take a minute on large files.</p>}
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

function ModelResults({ report }: { report: ModelReport }) {
  const top = report.importances[0]?.importance || 1;
  return (
    <div className="model-results" aria-label="Model results">
      <p>{report.summary}</p>
      <div className="scroll-table">
        <table className="data">
          <thead>
            <tr>
              <th>Model</th>
              <th className="num">{report.primary_metric}</th>
              <th className="num">± across folds</th>
              <th className="num">{report.secondary_metric}</th>
            </tr>
          </thead>
          <tbody>
            {report.scores.map((s) => (
              <tr key={s.name} className={s.name === report.best_model ? "best" : undefined}>
                <td>
                  {s.name}
                  {s.name === report.best_model && <span className="badge good">best</span>}
                </td>
                <td className="num">{report.task === "classification" ? `${(s.primary * 100).toFixed(1)}%` : s.primary.toFixed(3)}</td>
                <td className="num">{report.task === "classification" ? `${(s.primary_std * 100).toFixed(1)}` : s.primary_std.toFixed(3)}</td>
                <td className="num">{formatNumber(s.secondary)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {report.importances.length > 0 && (
        <>
          <h4>What matters most (random forest)</h4>
          <ul className="importance-list">
            {report.importances.map((i) => (
              <li key={i.feature}>
                <span className="importance-name">{i.feature}</span>
                <span className="importance-bar" style={{ width: `${(i.importance / top) * 100}%` }} />
                <span className="muted small">{(i.importance * 100).toFixed(1)}%</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="muted small">
        {report.rows_used.toLocaleString()} rows, {report.features.length} input columns, {report.folds}-fold
        cross-validation.{" "}
        {report.notes.join(" ")}
      </p>
    </div>
  );
}
