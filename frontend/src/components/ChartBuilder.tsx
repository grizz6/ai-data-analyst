import { lazy, Suspense, useState } from "react";
import { buildChart } from "../api";
import type { ChartSpec, ColumnProfile, CustomChartRequest, Explanation } from "../types";

// Shares the lazily loaded Plotly chunk with the main chart grid.
const ChartGrid = lazy(() => import("./ChartGrid"));

type ChartType = CustomChartRequest["chart_type"];
type Aggregate = CustomChartRequest["aggregate"];
type Kind = "number" | "date" | "text";
// One column picker: which columns fit it, and whether it can be left empty.
type Slot = { label: string; options: string[]; optional?: boolean };

const CHART_TYPES: { value: ChartType; label: string }[] = [
  { value: "bar", label: "Bar" },
  { value: "line", label: "Line" },
  { value: "scatter", label: "Scatter" },
  { value: "histogram", label: "Histogram" },
  { value: "box", label: "Box plot" },
];

const AGGREGATES: { value: Exclude<Aggregate, "count">; label: string }[] = [
  { value: "sum", label: "Total" },
  { value: "mean", label: "Average" },
  { value: "median", label: "Median" },
];

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

function columnKind(dtype: string): Kind {
  if (dtype.startsWith("datetime")) return "date";
  if (/^(u?int|float|Int|UInt|Float)/.test(dtype)) return "number";
  return "text";
}

interface Props {
  sessionId: string;
  columns: ColumnProfile[];
}

export default function ChartBuilder({ sessionId, columns }: Props) {
  // Identifier columns (order IDs, SKUs) are never charted, same as the automatic charts.
  const usable = columns.filter((c) => !c.is_identifier);
  const ofKind = (...kinds: Kind[]) => usable.filter((c) => kinds.includes(columnKind(c.dtype))).map((c) => c.name);
  const numbers = ofKind("number");
  const texts = ofKind("text");

  const [chartType, setChartType] = useState<ChartType>("bar");
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [aggregate, setAggregate] = useState<Exclude<Aggregate, "count">>("sum");
  const [charts, setCharts] = useState<ChartSpec[]>([]);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slots: Record<ChartType, { x?: Slot; y?: Slot }> = {
    bar: { x: { label: "Category", options: texts }, y: { label: "Value", options: numbers, optional: true } },
    line: { x: { label: "X axis", options: ofKind("date", "number") }, y: { label: "Value", options: numbers, optional: true } },
    scatter: { x: { label: "X axis", options: numbers }, y: { label: "Y axis", options: numbers } },
    histogram: { x: { label: "Column", options: numbers } },
    box: { y: { label: "Value", options: numbers }, x: { label: "Split by", options: texts, optional: true } },
  };
  const slot = slots[chartType];
  const aggregates = (chartType === "bar" || chartType === "line") && y !== "";
  const ready = (!slot.x || slot.x.optional || x !== "") && (!slot.y || slot.y.optional || y !== "");

  const changeType = (next: ChartType) => {
    setChartType(next);
    setX("");
    setY("");
    setError(null);
  };

  const handleBuild = async () => {
    setBuilding(true);
    setError(null);
    try {
      const spec = await buildChart(sessionId, {
        chart_type: chartType,
        x: slot.x && x ? x : null,
        y: slot.y && y ? y : null,
        aggregate: aggregates ? aggregate : "count",
      });
      // Newest first; building the same chart again just moves it to the top.
      setCharts((current) => [spec, ...current.filter((c) => c.id !== spec.id)]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Chart failed");
    } finally {
      setBuilding(false);
    }
  };

  if (numbers.length === 0 && texts.length === 0) {
    return <p className="muted">This file has no columns that can be charted.</p>;
  }

  const select = (
    id: string,
    spec: Slot,
    value: string,
    onChange: (v: string) => void,
    emptyLabel: string,
  ) => (
    <label className="builder-field" htmlFor={id}>
      <span>{spec.label}</span>
      <select id={id} className="builder-select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{spec.optional ? emptyLabel : "Choose…"}</option>
        {spec.options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <div className="builder-form">
        <label className="builder-field" htmlFor="builder-type">
          <span>Chart type</span>
          <select
            id="builder-type"
            className="builder-select"
            value={chartType}
            onChange={(e) => changeType(e.target.value as ChartType)}
          >
            {CHART_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        {slot.x && select("builder-x", slot.x, x, setX, chartType === "box" ? "No split" : "None")}
        {slot.y && select("builder-y", slot.y, y, setY, "Number of rows")}
        {aggregates && (
          <label className="builder-field" htmlFor="builder-agg">
            <span>Combine as</span>
            <select
              id="builder-agg"
              className="builder-select"
              value={aggregate}
              onChange={(e) => setAggregate(e.target.value as Exclude<Aggregate, "count">)}
            >
              {AGGREGATES.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <button type="button" className="btn" disabled={!ready || building} onClick={handleBuild}>
          {building ? "Building…" : "Build chart"}
        </button>
      </div>
      {error && <p className="error-msg">{error}</p>}
      {charts.length > 0 && (
        <>
          <div className="actions" style={{ marginTop: "1rem" }}>
            <button type="button" className="btn secondary" onClick={() => setCharts([])}>
              Clear built charts
            </button>
          </div>
          <Suspense fallback={<p className="muted">Loading charts…</p>}>
            <ChartGrid charts={charts} explanation={NO_NOTES} />
          </Suspense>
        </>
      )}
    </>
  );
}
