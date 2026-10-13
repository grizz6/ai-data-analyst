import type { Theme } from "./theme";

/**
 * Plotly's default template draws its own background, gridlines and palette,
 * which clash with the app. These overrides make every chart look like part
 * of the app, in light and dark mode.
 */
export const CHART_COLORS = ["#6366f1", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#06b6d4", "#f97316", "#64748b"];

const INK: Record<Theme, { text: string; grid: string; hover: string; border: string }> = {
  light: { text: "#334155", grid: "rgba(100, 116, 139, 0.16)", hover: "#ffffff", border: "#e2e8f0" },
  dark: { text: "#cbd5e1", grid: "rgba(148, 163, 184, 0.14)", hover: "#1e2433", border: "#2e3646" },
};

type Layout = Record<string, unknown>;

export function themedLayout(layout: Layout = {}, theme: Theme = "light"): Layout {
  const ink = INK[theme];
  const themed: Layout = {
    ...layout,
    // The card heading already shows the title, and Plotly's own would
    // collide with per-panel labels on narrow screens.
    title: undefined,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Inter Variable, Inter, system-ui, sans-serif", color: ink.text, size: 11.5 },
    colorway: CHART_COLORS,
    margin: { t: 36, r: 16, b: 44, l: 52 },
    // Grids of small charts set their own height; everything else is one size.
    height: typeof layout.height === "number" ? layout.height : 320,
    hoverlabel: { bgcolor: ink.hover, bordercolor: ink.border, font: { color: ink.text, family: "Inter Variable, Inter, sans-serif" } },
    legend: { ...((layout.legend as Layout | undefined) ?? {}), bgcolor: "rgba(0,0,0,0)" },
    bargap: typeof layout.bargap === "number" ? layout.bargap : 0.12,
  };
  // Subplots carry xaxis2, yaxis3 and so on; style every axis, not just the first.
  for (const key of new Set(["xaxis", "yaxis", ...Object.keys(layout)])) {
    if (/^[xy]axis\d*$/.test(key)) {
      themed[key] = {
        ...((layout[key] as Layout | undefined) ?? {}),
        gridcolor: ink.grid,
        zerolinecolor: ink.grid,
        linecolor: ink.grid,
      };
    }
  }
  return themed;
}

/**
 * Recolor single-color traces (bars, histograms, boxes) that Plotly Express pinned to its default blue.
 * Traces in the same legend group (a box and its outlier points, one category across a grid) share a color.
 */
export function themedData(data: Layout[], theme: Theme = "light"): Layout[] {
  const groupColors = new Map<unknown, string>();
  let next = 0;
  return data.map((trace) => {
    // Reference marks such as a median line take the text color.
    if (trace.meta === "foreground") {
      return { ...trace, line: { ...((trace.line as Layout | undefined) ?? {}), color: INK[theme].text } };
    }
    const group = trace.legendgroup;
    let color = group !== undefined ? groupColors.get(group) : undefined;
    if (color === undefined) {
      color = CHART_COLORS[next++ % CHART_COLORS.length];
      if (group !== undefined) groupColors.set(group, color);
    }
    const marker = (trace.marker as Layout | undefined) ?? {};
    // Heatmaps, anything colored by value, and traces that set meta "fixed-color"
    // (outliers drawn in red, say) keep their own colors.
    if (trace.type === "heatmap" || Array.isArray(marker.color) || trace.meta === "fixed-color") return trace;
    const recolored: Layout = { ...trace, marker: { ...marker, color } };
    // Box outlines and line traces draw with `line`; bars and histograms have none.
    if (trace.type === "scatter" || trace.type === "box") {
      recolored.line = { ...((trace.line as Layout | undefined) ?? {}), color };
    }
    return recolored;
  });
}
