import { lazy, Suspense } from "react";
import { formatNumber, formatP } from "../format";
import { variableTakeaway } from "../takeaways";
import type { VariableProfile } from "../types";
import { variableCharts } from "../variableCharts";
import Hint from "./Hint";
import Tile from "./Tile";

const ChartGrid = lazy(() => import("./ChartGrid"));

export const KIND_LABELS: Record<VariableProfile["kind"], string> = {
  binary: "Yes / no",
  number: "Number",
  count: "Count",
  category: "Category",
  date: "Date",
  identifier: "Identifier",
  text: "Free text",
  constant: "Constant",
};

const KIND_HINTS: Record<VariableProfile["kind"], string> = {
  binary: "Exactly two values (0/1, true/false, yes/no). Suits logistic regression as a target.",
  number: "A measurement on a continuous scale. Suits linear regression as a target.",
  count: "Whole numbers with few distinct values, such as number of children.",
  category: "Labels that repeat. Compared across groups; one-hot encoded for models.",
  date: "Dates or times: the axis for time-series analysis.",
  identifier: "Names a row (an ID or code). Kept out of statistics.",
  text: "Mostly unique text, such as names or notes.",
  constant: "The same value on every row.",
};

interface Props {
  variable: VariableProfile;
  onTrain?: (target: string) => void;
}

export default function VariableCard({ variable: v, onTrain }: Props) {
  const charts = variableCharts(v);
  const numeric = v.kind === "number" || v.kind === "count";
  return (
    <article className="variable-card" aria-label={`Variable ${v.name}`}>
      <header className="variable-head">
        <h3>{v.name}</h3>
        <span className="badge info" title={KIND_HINTS[v.kind]}>
          {KIND_LABELS[v.kind]}
        </span>
        <Hint text={KIND_HINTS[v.kind]} />
      </header>
      <p className="takeaway">{variableTakeaway(v)}</p>

      <div className="stats">
        <Tile label="Values" value={v.count.toLocaleString()} />
        <Tile label="Missing" value={`${formatNumber(v.missing_share)}%`} tone={v.missing_share >= 5 ? "attention" : undefined} />
        <Tile label="Distinct" value={v.distinct.toLocaleString()} />
        {numeric && (
          <>
            <Tile label="Mean" value={formatNumber(v.mean)} />
            <Tile label="Median" value={formatNumber(v.median)} />
            <Tile label="Std dev" value={formatNumber(v.std)} />
            <Tile label="Min" value={formatNumber(v.min)} />
            <Tile label="Max" value={formatNumber(v.max)} />
            <Tile
              label="Skewness"
              value={formatNumber(v.skewness)}
              hint="0 is symmetric; above 1 or below −1 means a long tail on one side"
            />
          </>
        )}
        {v.binary && (
          <Tile label={`Share ${v.binary.positive}`} value={`${formatNumber(v.binary.positive_share)}%`} />
        )}
        {v.outliers && (
          <Tile
            label="Outliers (IQR)"
            value={v.outliers.iqr_count.toLocaleString()}
            tone={v.outliers.iqr_count ? "attention" : "good"}
          />
        )}
      </div>

      {v.flags.length > 0 && (
        <ul className="flag-list">
          {v.flags.map((f) => (
            <li key={f}>{f}</li>
          ))}
        </ul>
      )}

      {charts.length > 0 && (
        <Suspense fallback={<p className="muted">Loading charts…</p>}>
          <ChartGrid charts={charts} />
        </Suspense>
      )}
      {v.beyond_view > 0 && v.view && (
        <p className="muted small">
          Zoomed to {formatNumber(v.view[0])} – {formatNumber(v.view[1])}: {v.beyond_view.toLocaleString()} far-out{" "}
          {v.beyond_view === 1 ? "value" : "values"} (beyond 3×IQR) would squash the histogram, box and violin, so
          they're left off and listed below.
        </p>
      )}

      {v.outliers && <Outliers v={v} />}
      {v.binary && <BinaryComparisons v={v} onTrain={onTrain} />}
    </article>
  );
}

function Outliers({ v }: { v: VariableProfile }) {
  const o = v.outliers!;
  return (
    <section className="stats-section" aria-label="Outliers">
      <h4>
        Outliers <Hint text="IQR rule: below Q1 − 1.5×IQR or above Q3 + 1.5×IQR. z rule: more than 3 standard deviations from the mean." />
      </h4>
      <div className="grid-2">
        <div className="scroll-table">
          <table className="data" aria-label="Outlier rules">
            <thead>
              <tr>
                <th>Rule</th>
                <th>Outside</th>
                <th className="num">Rows</th>
                <th className="num">Share</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>IQR (1.5×)</td>
                <td>
                  below {formatNumber(o.iqr_low)} or above {formatNumber(o.iqr_high)}
                </td>
                <td className="num">{o.iqr_count.toLocaleString()}</td>
                <td className="num">{formatNumber(o.iqr_share)}%</td>
              </tr>
              <tr>
                <td>z-score</td>
                <td>|z| &gt; {o.z_threshold}</td>
                <td className="num">{o.z_count.toLocaleString()}</td>
                <td className="num">{formatNumber(o.z_share)}%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="scroll-table">
          <table className="data" aria-label="With and without outliers">
            <thead>
              <tr>
                <th />
                <th className="num">All rows</th>
                <th className="num">Without IQR outliers</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Mean</td>
                <td className="num">{formatNumber(o.mean_all)}</td>
                <td className="num">{formatNumber(o.mean_without)}</td>
              </tr>
              <tr>
                <td>Median</td>
                <td className="num">{formatNumber(o.median_all)}</td>
                <td className="num">{formatNumber(o.median_without)}</td>
              </tr>
              <tr>
                <td>Std dev</td>
                <td className="num">{formatNumber(o.std_all)}</td>
                <td className="num">{formatNumber(o.std_without)}</td>
              </tr>
              {o.correlation && (
                <tr>
                  <td>r with {o.correlation.column}</td>
                  <td className="num">{o.correlation.r_all.toFixed(3)}</td>
                  <td className="num">{o.correlation.r_without.toFixed(3)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {o.rows.length > 0 && (
        <div className="scroll-table">
          <table className="data" aria-label="Most extreme values">
            <thead>
              <tr>
                <th className="num">Row</th>
                {o.rows.some((r) => r.label) && <th>ID</th>}
                <th className="num">Value</th>
                <th className="num">z</th>
                <th>Rules</th>
                <th>Likely cause</th>
              </tr>
            </thead>
            <tbody>
              {o.rows.map((r) => (
                <tr key={`${r.row}-${r.value}`}>
                  <td className="num">{r.row || "–"}</td>
                  {o.rows.some((x) => x.label) && <td>{r.label ?? "–"}</td>}
                  <td className="num">{formatNumber(r.value)}</td>
                  <td className="num">{r.z === null ? "–" : r.z.toFixed(1)}</td>
                  <td>{r.rules.join(" + ")}</td>
                  <td>{r.cause}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function BinaryComparisons({ v, onTrain }: { v: VariableProfile; onTrain?: (target: string) => void }) {
  const b = v.binary!;
  return (
    <section className="stats-section" aria-label="What differs between the groups">
      <div className="section-head">
        <h4>
          What differs between {b.positive} and the rest{" "}
          <Hint text="Numbers: rank-biserial correlation (−1 to 1; positive means higher when the value is the counted one). Categories: Cramér's V (0 to 1). p-values adjusted for testing many columns." />
        </h4>
        {onTrain && (
          <button type="button" className="btn small-btn" onClick={() => onTrain(v.name)}>
            Train models on {v.name}
          </button>
        )}
      </div>
      {v.compared.length === 0 ? (
        <p className="muted">No other column to compare.</p>
      ) : (
        <div className="scroll-table">
          <table className="data" aria-label={`Compared against ${v.name}`}>
            <thead>
              <tr>
                <th>Column</th>
                <th className="num">Effect</th>
                <th>Adjusted p</th>
                <th>Detail</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {v.compared.map((c) => (
                <tr key={c.column}>
                  <td>{c.column}</td>
                  <td className="num" title={c.effect_name}>
                    {c.effect.toFixed(2)}
                  </td>
                  <td>{formatP(c.p_value)}</td>
                  <td>{c.detail}</td>
                  <td>
                    {c.p_value !== null && c.p_value < 0.05 ? (
                      <span className="badge good">likely real</span>
                    ) : (
                      <span className="badge info">could be chance</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
