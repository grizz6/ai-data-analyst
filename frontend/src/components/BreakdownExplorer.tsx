import { lazy, Suspense, useState } from "react";
import { breakdownChart, crosstabChart } from "../breakdownCharts";
import { formatNumber, formatP } from "../format";
import type { CategoryBreakdown, CategoryCrosstab } from "../types";
import Hint from "./Hint";

const ChartGrid = lazy(() => import("./ChartGrid"));

interface Props {
  breakdowns: CategoryBreakdown[];
  crosstabs: CategoryCrosstab[];
}

function strongest<T>(items: T[], score: (item: T) => number): T | undefined {
  return items.reduce<T | undefined>((best, item) => (best === undefined || score(item) > score(best) ? item : best), undefined);
}

/** Pick any category and number to compare, or any two categories to cross. */
export default function BreakdownExplorer({ breakdowns, crosstabs }: Props) {
  const first = strongest(breakdowns, (b) => b.eta_squared);
  const [category, setCategory] = useState(first?.category ?? "");
  const [value, setValue] = useState(first?.value ?? "");
  const firstPair = crosstabs[0];
  const [pair, setPair] = useState(firstPair ? `${firstPair.row}|${firstPair.column}` : "");
  const [rowShare, setRowShare] = useState(true);

  if (!breakdowns.length && !crosstabs.length) return null;

  const categories = [...new Set(breakdowns.map((b) => b.category))];
  const values = breakdowns.filter((b) => b.category === category).map((b) => b.value);
  const shown = breakdowns.find((b) => b.category === category && b.value === value);
  const table = crosstabs.find((c) => `${c.row}|${c.column}` === pair);

  return (
    <div className="explorers">
      {breakdowns.length > 0 && (
        <section className="stats-section" aria-label="A number by group">
          <h3>
            A number by group{" "}
            <Hint text="Box plot of a numeric column within each group of a category. 'Explained' is eta squared: the share of the number's variation the groups account for." />
          </h3>
          <div className="builder-form">
            <label className="builder-field">
              <span>Group by</span>
              <select
                className="builder-select"
                value={category}
                onChange={(e) => {
                  const next = e.target.value;
                  setCategory(next);
                  const options = breakdowns.filter((b) => b.category === next);
                  if (!options.some((b) => b.value === value)) setValue(strongest(options, (b) => b.eta_squared)?.value ?? "");
                }}
              >
                {categories.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="builder-field">
              <span>Number</span>
              <select className="builder-select" value={value} onChange={(e) => setValue(e.target.value)}>
                {values.map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
          </div>
          {shown && (
            <>
              <p className="takeaway small-takeaway">
                {shown.category} explains {formatNumber(Math.round(shown.eta_squared * 1000) / 10)}% of {shown.value} ·
                highest {shown.groups[0].label} (median {formatNumber(shown.groups[0].box.median)}) · lowest{" "}
                {shown.groups[shown.groups.length - 1].label} (median{" "}
                {formatNumber(shown.groups[shown.groups.length - 1].box.median)}) · {formatP(shown.p_value)}
              </p>
              <Suspense fallback={<p className="muted">Loading chart…</p>}>
                <ChartGrid charts={[breakdownChart(shown)]} />
              </Suspense>
            </>
          )}
        </section>
      )}

      {crosstabs.length > 0 && (
        <section className="stats-section" aria-label="Two categories together">
          <h3>
            Two categories together{" "}
            <Hint text="How often each pair of values occurs. Cramér's V runs from 0 (unrelated) to 1 (one determines the other)." />
          </h3>
          <div className="builder-form">
            <label className="builder-field">
              <span>Categories</span>
              <select className="builder-select" value={pair} onChange={(e) => setPair(e.target.value)}>
                {crosstabs.map((c) => (
                  <option key={`${c.row}|${c.column}`} value={`${c.row}|${c.column}`}>
                    {c.row} × {c.column} (V {c.cramers_v.toFixed(2)})
                  </option>
                ))}
              </select>
            </label>
            <label className="builder-check">
              <input type="checkbox" checked={rowShare} onChange={(e) => setRowShare(e.target.checked)} /> Row %
            </label>
          </div>
          {table && (
            <>
              <p className="takeaway small-takeaway">
                Cramér's V {table.cramers_v.toFixed(2)} · {formatP(table.p_value)}
                {table.p_value !== null && table.p_value < 0.05 ? " · related" : " · could be chance"}
              </p>
              <Suspense fallback={<p className="muted">Loading chart…</p>}>
                <ChartGrid charts={[crosstabChart(table, rowShare)]} />
              </Suspense>
            </>
          )}
        </section>
      )}
    </div>
  );
}
