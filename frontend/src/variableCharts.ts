/**
 * Charts for one variable, built in the browser from the numbers the server
 * sent (bins, density curve, quantiles, box statistics), so a file's charts
 * cost kilobytes rather than every raw value.
 */
import type { BoxStats, ChartSpec, VariableProfile } from "./types";

const OUTLIER = "#f87171";
const OUTLIER_ZONE = "rgba(248, 113, 113, 0.12)";
const REFERENCE = "#8fa3bc";
const HEIGHT = 280;

type Trace = Record<string, unknown>;

function spec(id: string, title: string, chartType: string, data: Trace[], layout: Record<string, unknown>): ChartSpec {
  return { id, title, chart_type: chartType, plotly_json: { data, layout: { height: HEIGHT, showlegend: false, ...layout } } };
}

/** Listed outliers inside the zoomed range; far-out ones stay in the table. */
function outlierValues(v: VariableProfile): number[] {
  const values = v.outliers?.rows.map((r) => r.value) ?? [];
  if (!v.view) return values;
  const [low, high] = v.view;
  return values.filter((x) => x >= low && x <= high);
}

/** The value axis, zoomed past far-out values when the server chose a view. */
function valueAxis(v: VariableProfile): Record<string, unknown> {
  if (!v.view) return { title: { text: v.name } };
  const [low, high] = v.view;
  const pad = (high - low) * 0.05 || 1;
  return { title: { text: v.name }, range: [low - pad, high + pad] };
}

function boxTrace(name: string, box: BoxStats): Trace {
  return {
    type: "box",
    name,
    x: [name],
    q1: [box.q1],
    median: [box.median],
    q3: [box.q3],
    lowerfence: [box.low],
    upperfence: [box.high],
    mean: [box.mean],
    boxpoints: false,
    hoverinfo: "y",
  };
}

function outlierPoints(name: string, values: number[]): Trace {
  return {
    type: "scatter",
    mode: "markers",
    x: values.map(() => name),
    y: values,
    marker: { color: OUTLIER, size: 7, symbol: "circle-open" },
    name: "outliers",
    meta: "fixed-color",
    hovertemplate: "%{y}<extra>outlier</extra>",
  };
}

/** Histogram with the values outside the IQR fences shaded. */
export function histogramChart(v: VariableProfile): ChartSpec | null {
  const h = v.histogram;
  if (!h) return null;
  const centers = h.counts.map((_, i) => (h.edges[i] + h.edges[i + 1]) / 2);
  const width = h.edges[1] - h.edges[0];
  const shapes: Trace[] = [];
  const o = v.outliers;
  if (o && o.iqr_count > 0) {
    const first = h.edges[0];
    const last = h.edges[h.edges.length - 1];
    if (o.iqr_low > first) shapes.push(zone(first, o.iqr_low));
    if (o.iqr_high < last) shapes.push(zone(o.iqr_high, last));
  }
  return spec(
    "histogram",
    "Histogram",
    "histogram",
    [{ type: "bar", x: centers, y: h.counts, width, hovertemplate: "%{x}<br>%{y} rows<extra></extra>" }],
    { bargap: 0.03, xaxis: { title: { text: v.name } }, yaxis: { title: { text: "rows" } }, shapes },
  );
}

function zone(x0: number, x1: number): Trace {
  return { type: "rect", xref: "x", yref: "paper", x0, x1, y0: 0, y1: 1, fillcolor: OUTLIER_ZONE, line: { width: 0 }, layer: "below" };
}

/** Box plot with the listed outliers marked. */
export function boxChart(v: VariableProfile): ChartSpec | null {
  if (!v.box) return null;
  const data = [boxTrace(v.name, v.box)];
  const points = outlierValues(v);
  if (points.length) data.push(outlierPoints(v.name, points));
  return spec("box", "Box plot", "box", data, { yaxis: valueAxis(v) });
}

/** Violin: the density curve mirrored, with the median and the outliers. */
export function violinChart(v: VariableProfile): ChartSpec | null {
  const d = v.density;
  if (!d || !v.box) return null;
  const xs = d.x as number[];
  const peak = Math.max(...d.y) || 1;
  const half = d.y.map((y) => (0.45 * y) / peak);
  const outline: Trace = {
    type: "scatter",
    mode: "lines",
    x: [...half, ...half.map((w) => -w).reverse()],
    y: [...xs, ...[...xs].reverse()],
    fill: "toself",
    hoverinfo: "skip",
    name: v.name,
  };
  const median: Trace = {
    type: "scatter",
    mode: "lines",
    x: [-0.25, 0.25],
    y: [v.box.median, v.box.median],
    line: { color: "#e8eef5", width: 2 },
    meta: "fixed-color",
    name: "median",
    hovertemplate: `median ${v.box.median}<extra></extra>`,
  };
  const data = [outline, median];
  const points = outlierValues(v);
  if (points.length) {
    data.push({ ...outlierPoints(v.name, points), x: points.map(() => 0) });
  }
  return spec("violin", "Violin plot", "violin", data, {
    xaxis: { visible: false, range: [-0.6, 0.6] },
    yaxis: valueAxis(v),
  });
}

/** Sample quantiles against a normal distribution's; on the line means normal-shaped. */
export function qqChart(v: VariableProfile): ChartSpec | null {
  const q = v.qq;
  if (!q || v.mean === null || v.std === null) return null;
  const xs = q.x as number[];
  const ends = [xs[0], xs[xs.length - 1]];
  return spec(
    "qq",
    "Q-Q plot against a normal distribution",
    "scatter",
    [
      { type: "scatter", mode: "markers", x: xs, y: q.y, marker: { size: 5 }, name: v.name },
      {
        type: "scatter",
        mode: "lines",
        x: ends,
        y: ends.map((t) => v.mean! + v.std! * t),
        line: { color: REFERENCE, dash: "dot" },
        meta: "fixed-color",
        name: "normal",
        hoverinfo: "skip",
      },
    ],
    { xaxis: { title: { text: "normal quantiles" } }, yaxis: valueAxis(v) },
  );
}

export function timelineChart(v: VariableProfile): ChartSpec | null {
  const t = v.timeline;
  if (!t) return null;
  const rate = v.kind === "binary" && v.binary;
  return spec(
    "timeline",
    rate ? `Share of ${v.binary!.positive} over time` : v.kind === "date" ? "Rows over time" : "Over time",
    v.kind === "date" ? "bar" : "line",
    [
      v.kind === "date"
        ? { type: "bar", x: t.x, y: t.y }
        : { type: "scatter", mode: "lines", x: t.x, y: rate ? t.y.map((y) => y * 100) : t.y, name: v.name },
    ],
    { yaxis: { title: { text: rate ? `% ${v.binary!.positive}` : v.kind === "date" ? "rows" : v.name } } },
  );
}

/** The variable for each side of every binary column, side by side. */
export function splitCharts(v: VariableProfile): ChartSpec[] {
  return v.splits.map((split) =>
    spec(
      `split-${split.binary_column}`,
      `By ${split.binary_column}`,
      "box",
      split.groups.map((g) => boxTrace(g.label, g.box)),
      { yaxis: { title: { text: v.name } } },
    ),
  );
}

export function categoryChart(v: VariableProfile): ChartSpec | null {
  if (!v.categories.length) return null;
  const rows = [...v.categories].reverse();
  return spec(
    "categories",
    "Count of each value",
    "bar",
    [
      {
        type: "bar",
        orientation: "h",
        x: rows.map((c) => c.count),
        y: rows.map((c) => c.value),
        customdata: rows.map((c) => c.share),
        hovertemplate: "%{y}: %{x} rows (%{customdata}%)<extra></extra>",
      },
    ],
    { height: Math.max(HEIGHT, 26 * rows.length + 80), yaxis: { automargin: true } },
  );
}

export function binaryChart(v: VariableProfile): ChartSpec | null {
  const b = v.binary;
  if (!b) return null;
  return spec(
    "binary",
    "Split",
    "bar",
    [{ type: "bar", x: b.values, y: b.counts, hovertemplate: "%{x}: %{y} rows<extra></extra>" }],
    { yaxis: { title: { text: "rows" } } },
  );
}

/** Every chart that fits this variable, most telling first. */
export function variableCharts(v: VariableProfile): ChartSpec[] {
  const charts =
    v.kind === "binary"
      ? [binaryChart(v), timelineChart(v)]
      : v.kind === "category" || v.kind === "text"
        ? [categoryChart(v)]
        : v.kind === "date"
          ? [timelineChart(v)]
          : [histogramChart(v), boxChart(v), violinChart(v), qqChart(v), timelineChart(v), ...splitCharts(v)];
  return charts.filter((c): c is ChartSpec => c !== null);
}
