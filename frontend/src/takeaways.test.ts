import { describe, expect, it } from "vitest";
import {
  clusteringTakeaway,
  exploreTakeaway,
  overviewTakeaway,
  qualityTakeaway,
  relationshipsTakeaway,
  timeSeriesTakeaway,
} from "./takeaways";
import { sampleResult } from "./test/fixtures";

describe("takeaways", () => {
  it("sums filled cells across columns", () => {
    const result = sampleResult();
    result.columns = result.columns.map((c, i) => (i === 0 ? { ...c, null_count: 31, non_null_count: 0 } : c));
    expect(overviewTakeaway(result)).toBe("31 rows × 5 columns · 80% of cells filled");
  });

  it("names the column with the most gaps", () => {
    const result = sampleResult({
      quality_issues: [{ category: "missing", column: "units", details: {}, message: "", severity: "warning" }],
    });
    result.columns = result.columns.map((c) => (c.name === "units" ? { ...c, null_pct: 12.9 } : c));
    expect(qualityTakeaway(result)).toMatch(/^1 issue \(1 to check\) · most gaps: units \(12\.9%\) · \d+ cleaning steps?$/);
    expect(qualityTakeaway(sampleResult({ quality_issues: [] }))).toBe("No quality issues found.");
  });

  it("points out the most skewed column only when it is clearly skewed", () => {
    const result = sampleResult();
    const base = result.statistics.distributions[0];
    result.statistics.distributions = [
      { ...base, column: "a", skewness: 0.4, zscore_outliers: 0 },
      { ...base, column: "b", skewness: -2.25, zscore_outliers: 3 },
    ];
    expect(exploreTakeaway(result)).toMatch(/most skewed: b \(-2\.3\) · 3 extreme values/);
    result.statistics.distributions = [{ ...base, skewness: 0.4, zscore_outliers: 0 }];
    expect(exploreTakeaway(result)).not.toMatch(/skewed|extreme/);
  });

  it("leads with the strongest correlation, whatever its sign", () => {
    const result = sampleResult();
    const base = result.correlations[0];
    result.correlations = [
      { ...base, column_a: "a", column_b: "b", correlation: 0.3 },
      { ...base, column_a: "c", column_b: "d", correlation: -0.71 },
    ];
    result.statistics.group_differences = [];
    expect(relationshipsTakeaway(result)).toBe("Strongest link: c ↔ d (r = -0.71)");
    expect(relationshipsTakeaway(sampleResult({ correlations: [] }))).not.toMatch(/Strongest/);
  });

  it("counts series, seasonal ones and forecasts", () => {
    const result = sampleResult();
    expect(timeSeriesTakeaway(result)).toMatch(/^\d+ series over date/);
  });

  it("says plainly when there are no clear groups", () => {
    const result = sampleResult();
    expect(clusteringTakeaway(result)).toMatch(/^3 distinct groups \(silhouette 0\.87\) · largest \d+ rows$/);
    result.clustering = { ...result.clustering!, clear: false, silhouette: 0.12 };
    expect(clusteringTakeaway(result)).toBe("No clear groups (best silhouette 0.12, at 3 groups)");
    expect(clusteringTakeaway(sampleResult({ clustering: null }))).toMatch(/needs at least two numeric columns/);
  });
});
