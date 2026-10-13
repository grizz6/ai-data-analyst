/** Charts for the Relationships tab's explorers, built from the server's group statistics. */
import type { CategoryBreakdown, CategoryCrosstab, ChartSpec } from "./types";
import { boxTrace } from "./variableCharts";

export function breakdownChart(b: CategoryBreakdown): ChartSpec {
  return {
    id: `breakdown-${b.category}-${b.value}`,
    title: `${b.value} by ${b.category}`,
    chart_type: "box",
    plotly_json: {
      data: b.groups.map((g) => boxTrace(g.label, g.box)),
      layout: {
        height: 340,
        showlegend: false,
        xaxis: { title: { text: b.category } },
        yaxis: { title: { text: b.value } },
      },
    },
  };
}

/** Counts as a heatmap; with `rowShare`, each row as percentages of its total. */
export function crosstabChart(c: CategoryCrosstab, rowShare: boolean): ChartSpec {
  const z = c.counts.map((row) => {
    const total = row.reduce((a, b) => a + b, 0) || 1;
    return rowShare ? row.map((n) => Math.round((1000 * n) / total) / 10) : row;
  });
  return {
    id: `crosstab-${c.row}-${c.column}`,
    title: `${c.row} × ${c.column}`,
    chart_type: "heatmap",
    plotly_json: {
      data: [
        {
          type: "heatmap",
          x: c.column_labels,
          y: c.row_labels,
          z,
          text: z.map((row) => row.map((v) => (rowShare ? `${v}%` : String(v)))),
          texttemplate: "%{text}",
          colorscale: "Blues",
          hovertemplate: `${c.row} %{y}, ${c.column} %{x}: %{text}<extra></extra>`,
        },
      ],
      layout: {
        height: Math.max(300, 34 * c.row_labels.length + 120),
        xaxis: { title: { text: c.column } },
        yaxis: { title: { text: c.row }, automargin: true, autorange: "reversed" },
      },
    },
  };
}
