import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { sampleResult } from "../test/fixtures";
import ClusteringPanel from "./ClusteringPanel";

vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: { title: string }[] }) => (
    <div data-testid="charts">{charts.map((c) => c.title).join(", ")}</div>
  ),
}));

describe("ClusteringPanel", () => {
  it("shows the groups found, with what makes each stand out", async () => {
    const result = sampleResult();
    render(<ClusteringPanel clustering={result.clustering} charts={[]} />);
    expect(screen.getAllByText(/^Group \d$/)).toHaveLength(3);
    expect(screen.getByText("0.87")).toBeInTheDocument();
    // Without the per-tab charts it still draws the PCA map.
    expect(await screen.findByTestId("charts")).toHaveTextContent("Groups of similar rows");
  });

  it("explains when there's nothing to group", () => {
    render(<ClusteringPanel clustering={null} charts={[]} />);
    expect(screen.getByText(/needs at least two numeric columns and 50 rows/)).toBeInTheDocument();
  });
});
