/**
 * Plotly's default template draws white gridlines and its own palette, which
 * clash with the app's dark theme. These overrides make every chart, the
 * automatic ones and those from the builder, look like part of the app.
 */
export const CHART_COLORS = ["#4f8cff", "#34d399", "#fbbf24", "#f472b6", "#a78bfa", "#22d3ee", "#fb923c", "#94a3b8"];

const GRID = "rgba(143, 163, 188, 0.18)";

type Layout = Record<string, unknown>;

export function themedLayout(layout: Layout = {}): Layout {
  const themed: Layout = {
    ...layout,
    // The card heading already shows the title, and Plotly's own would
    // collide with per-panel labels on narrow screens.
    title: undefined,
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: { color: "#e8eef5", size: 11 },
    colorway: CHART_COLORS,
    margin: { t: 36, r: 16, b: 40, l: 48 },
    height: 320,
    hoverlabel: { bgcolor: "#1a2533", bordercolor: "#2a3a4f", font: { color: "#e8eef5" } },
  };
  // Subplots carry xaxis2, yaxis3 and so on; style every axis, not just the first.
  for (const key of new Set(["xaxis", "yaxis", ...Object.keys(layout)])) {
    if (/^[xy]axis\d*$/.test(key)) {
      themed[key] = { ...((layout[key] as Layout | undefined) ?? {}), gridcolor: GRID, zerolinecolor: GRID, linecolor: GRID };
    }
  }
  return themed;
}

/** Recolor single-color traces (bars, histograms, boxes) that Plotly Express pinned to its default blue. */
export function themedData(data: Layout[]): Layout[] {
  return data.map((trace, i) => {
    const color = CHART_COLORS[i % CHART_COLORS.length];
    const marker = (trace.marker as Layout | undefined) ?? {};
    // Heatmaps and anything colored by value keep their own scale.
    if (trace.type === "heatmap" || Array.isArray(marker.color)) return trace;
    const recolored: Layout = { ...trace, marker: { ...marker, color } };
    // Box outlines and line traces draw with `line`; bars and histograms have none.
    if (trace.type === "scatter" || trace.type === "box") {
      recolored.line = { ...((trace.line as Layout | undefined) ?? {}), color };
    }
    return recolored;
  });
}
