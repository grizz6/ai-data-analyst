import { describe, expect, it } from "vitest";
import {
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

  it("counts series and seasonal ones", () => {
    const result = sampleResult();
    expect(timeSeriesTakeaway(result)).toMatch(/^\d+ series over date/);
  });
});
