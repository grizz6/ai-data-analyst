import { describe, expect, it } from "vitest";
import { sampleResult } from "./test/fixtures";
import { boxChart, histogramChart, qqChart, variableCharts, violinChart } from "./variableCharts";

const sales = () => sampleResult().variables.find((v) => v.name === "sales")!;

describe("variableCharts", () => {
  it("draws every chart a number gets from the profile's data", () => {
    expect(variableCharts(sales()).map((c) => c.id)).toEqual(["histogram", "box", "violin", "qq", "timeline"]);
  });

  it("puts one bar per bin at the bin's centre", () => {
    const v = sales();
    const bar = (histogramChart(v)!.plotly_json as { data: { x: number[]; y: number[] }[] }).data[0];
    expect(bar.y).toEqual(v.histogram!.counts);
    expect(bar.x[0]).toBeCloseTo((v.histogram!.edges[0] + v.histogram!.edges[1]) / 2);
  });

  it("shades the outlier zones and marks outliers in red", () => {
    const v = sales();
    v.outliers = { ...v.outliers!, iqr_count: 1, iqr_high: v.max! - 1, rows: [{ row: 3, value: v.max!, z: 3.2, rules: ["IQR"], cause: "", label: null }] };
    const layout = (histogramChart(v)!.plotly_json as { layout: { shapes: unknown[] } }).layout;
    expect(layout.shapes).toHaveLength(1);
    const traces = (boxChart(v)!.plotly_json as { data: { meta?: string; y?: number[] }[] }).data;
    expect(traces[1]).toMatchObject({ meta: "fixed-color", y: [v.max] });
  });

  it("mirrors the density for the violin and draws the normal line on the Q-Q plot", () => {
    const v = sales();
    const outline = (violinChart(v)!.plotly_json as { data: { x: number[] }[] }).data[0];
    expect(outline.x.length).toBe(2 * v.density!.x.length);
    expect(Math.max(...outline.x)).toBeCloseTo(-Math.min(...outline.x));
    const line = (qqChart(v)!.plotly_json as { data: { y: number[] }[] }).data[1];
    expect(line.y[0]).toBeCloseTo(v.mean! + v.std! * (v.qq!.x[0] as number));
  });
});
