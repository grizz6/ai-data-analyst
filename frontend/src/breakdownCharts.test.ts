import { describe, expect, it } from "vitest";
import { breakdownChart, crosstabChart } from "./breakdownCharts";
import { sampleResult } from "./test/fixtures";

describe("breakdownCharts", () => {
  it("draws one box per group, in the server's order", () => {
    const b = sampleResult().breakdowns[0];
    const data = (breakdownChart(b).plotly_json as { data: { name: string; median: number[] }[] }).data;
    expect(data.map((t) => t.name)).toEqual(b.groups.map((g) => g.label));
    expect(data[0].median).toEqual([b.groups[0].box.median]);
  });

  it("shows counts, or each row as percentages of its total", () => {
    const c = { ...sampleResult().crosstabs[0], counts: [[1, 3], [2, 2]], row_labels: ["a", "b"], column_labels: ["x", "y"] };
    const z = (rowShare: boolean) => (crosstabChart(c, rowShare).plotly_json as { data: { z: number[][] }[] }).data[0].z;
    expect(z(false)).toEqual([[1, 3], [2, 2]]);
    expect(z(true)).toEqual([[25, 75], [50, 50]]);
  });
});
