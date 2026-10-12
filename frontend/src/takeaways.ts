import { formatNumber } from "./format";
import type { AnalysisResult } from "./types";

/** One line per dashboard tab, built from the computed numbers only. */

function pct(value: number) {
  return `${formatNumber(value)}%`;
}

export function overviewTakeaway(r: AnalysisResult): string {
  const cells = r.columns.reduce((sum, c) => sum + c.null_count + c.non_null_count, 0);
  const filled = r.columns.reduce((sum, c) => sum + c.non_null_count, 0);
  const share = cells ? (filled / cells) * 100 : 100;
  return `${r.row_count.toLocaleString()} rows × ${r.column_count} columns · ${pct(Math.round(share * 10) / 10)} of cells filled`;
}

export function qualityTakeaway(r: AnalysisResult): string {
  if (r.quality_issues.length === 0) return "No quality issues found.";
  const serious = r.quality_issues.filter((i) => i.severity === "error" || i.severity === "warning").length;
  const gaps = [...r.columns].sort((a, b) => b.null_pct - a.null_pct)[0];
  const parts = [`${r.quality_issues.length} issue${r.quality_issues.length === 1 ? "" : "s"} (${serious} to check)`];
  if (gaps && gaps.null_pct > 0) parts.push(`most gaps: ${gaps.name} (${pct(gaps.null_pct)})`);
  parts.push(`${r.cleaning_actions.length} cleaning step${r.cleaning_actions.length === 1 ? "" : "s"}`);
  return parts.join(" · ");
}

export function exploreTakeaway(r: AnalysisResult): string {
  const skewed = r.statistics.distributions
    .filter((d) => d.skewness !== null)
    .sort((a, b) => Math.abs(b.skewness!) - Math.abs(a.skewness!))[0];
  const parts = [`${r.numeric_summaries.length} numeric · ${r.categorical_summaries.length} category columns`];
  if (skewed && Math.abs(skewed.skewness!) >= 1) parts.push(`most skewed: ${skewed.column} (${skewed.skewness!.toFixed(1)})`);
  const outliers = r.statistics.distributions.reduce((sum, d) => sum + d.zscore_outliers, 0);
  if (outliers > 0) parts.push(`${outliers.toLocaleString()} extreme value${outliers === 1 ? "" : "s"} (|z| > 3)`);
  return parts.join(" · ");
}

export function relationshipsTakeaway(r: AnalysisResult): string {
  const pair = [...r.correlations].sort((a, b) => Math.abs(b.correlation) - Math.abs(a.correlation))[0];
  const group = [...r.statistics.group_differences].sort((a, b) => b.eta_squared - a.eta_squared)[0];
  const parts: string[] = [];
  if (pair) parts.push(`Strongest link: ${pair.column_a} ↔ ${pair.column_b} (r = ${pair.correlation.toFixed(2)})`);
  if (group && group.eta_squared >= 0.06) {
    parts.push(`${group.group_column} explains ${Math.round(group.eta_squared * 100)}% of ${group.value_column}`);
  }
  return parts.length ? parts.join(" · ") : "No strong links between columns.";
}

export function timeSeriesTakeaway(r: AnalysisResult): string {
  const seasonal = r.time_series.filter((t) => (t.seasonal_strength ?? 0) >= 0.4).length;
  const axis = r.time_axis ? ` over ${r.time_axis.label}` : "";
  const parts = [`${r.time_series.length} series${axis}`];
  if (seasonal) parts.push(`${seasonal} with a clear repeating pattern`);
  const forecasts = r.time_series.filter((t) => t.forecast.length > 0).length;
  if (forecasts) parts.push(`${forecasts} with a forecast`);
  return parts.join(" · ");
}

export function clusteringTakeaway(r: AnalysisResult): string {
  const c = r.clustering;
  if (!c) return "Grouping needs at least two numeric columns and 50 rows.";
  return c.clear
    ? `${c.k} distinct groups (silhouette ${c.silhouette.toFixed(2)}) · largest ${c.clusters[0].size.toLocaleString()} rows`
    : `No clear groups (best silhouette ${c.silhouette.toFixed(2)}, at ${c.k} groups)`;
}
