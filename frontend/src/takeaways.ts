import { formatNumber } from "./format";
import type { AnalysisResult, VariableProfile } from "./types";

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
  return parts.join(" · ");
}

/** One line for a single column, by its kind. */
export function variableTakeaway(v: VariableProfile): string {
  if (v.kind === "number" || v.kind === "count") {
    const parts = [`median ${formatNumber(v.median)}`, `range ${formatNumber(v.min)} to ${formatNumber(v.max)}`];
    const o = v.outliers;
    if (o) parts.push(o.iqr_count ? `${o.iqr_count.toLocaleString()} outliers (${formatNumber(o.iqr_share)}%)` : "no outliers");
    return parts.join(" · ");
  }
  if (v.kind === "binary" && v.binary) {
    const b = v.binary;
    const split = b.values.map((value, i) => `${formatNumber((100 * b.counts[i]) / (b.counts[0] + b.counts[1]))}% ${value}`);
    const top = v.compared[0];
    const parts = [split.join(" / ")];
    if (top && top.p_value !== null && top.p_value < 0.05) parts.push(`differs most by ${top.column}`);
    return parts.join(" · ");
  }
  if (v.kind === "category" && v.categories.length) {
    const top = v.categories[0];
    return `${v.distinct.toLocaleString()} values · most common '${top.value}' (${formatNumber(top.share)}%)`;
  }
  return v.flags[0] ?? `${v.distinct.toLocaleString()} distinct values`;
}

export function variablesTakeaway(r: AnalysisResult): string {
  const count = (kinds: string[]) => r.variables.filter((v) => kinds.includes(v.kind)).length;
  const parts = [`${r.variables.length} columns: ${count(["number", "count"])} numeric, ${count(["binary"])} yes/no, ${count(["category"])} category`];
  const withOutliers = r.variables.filter((v) => (v.outliers?.iqr_count ?? 0) > 0).length;
  if (withOutliers) parts.push(`${withOutliers} with outliers`);
  return parts.join(" · ");
}

export function suggestionsTakeaway(r: AnalysisResult): string {
  const recs = r.recommendations;
  if (!recs.length) return "No follow-up analysis stands out for this data.";
  const ready = recs.filter((x) => x.readiness === "ready").length;
  const work = recs.filter((x) => x.readiness === "needs_work").length;
  const weak = recs.length - ready - work;
  const parts = [`${recs.length} analyses this data supports`, `${ready} ready`, `${work} need work first`];
  if (weak) parts.push(`${weak} on weak evidence`);
  return parts.join(" · ");
}
