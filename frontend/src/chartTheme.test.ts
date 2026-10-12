import { describe, expect, it } from "vitest";
import { CHART_COLORS, themedData, themedLayout } from "./chartTheme";

describe("chart theme", () => {
  it("dims the gridlines on every axis, subplots included", () => {
    const layout = themedLayout({ title: { text: "x" }, xaxis2: { title: "b" }, yaxis3: {} });
    for (const axis of ["xaxis", "yaxis", "xaxis2", "yaxis3"]) {
      expect(layout[axis]).toMatchObject({ gridcolor: expect.stringContaining("rgba") });
    }
    expect(layout.xaxis2).toMatchObject({ title: "b" });
    expect(layout.title).toBeUndefined();
  });

  it("recolors plain traces but leaves heatmaps and per-point colors alone", () => {
    const heatmap = { type: "heatmap", colorscale: "RdBu" };
    const perPoint = { type: "bar", marker: { color: ["red", "blue"] } };
    const [bar, box, heat, points] = themedData([
      { type: "bar", marker: { color: "#636efa" } },
      { type: "box" },
      heatmap,
      perPoint,
    ]);
    expect(bar.marker).toEqual({ color: CHART_COLORS[0] });
    expect(bar.line).toBeUndefined();
    expect(box.line).toEqual({ color: CHART_COLORS[1] });
    expect(heat).toBe(heatmap);
    expect(points).toBe(perPoint);
  });

  it("gives traces in one legend group one color", () => {
    const [box, outliers, other, again] = themedData([
      { type: "box", legendgroup: "a" },
      { type: "scatter", legendgroup: "a" },
      { type: "box", legendgroup: "b" },
      { type: "scatter", legendgroup: "b" },
    ]);
    expect(outliers.marker).toEqual(box.marker);
    expect(other.marker).toEqual({ color: CHART_COLORS[1] });
    expect(again.marker).toEqual({ color: CHART_COLORS[1] });
  });
});
