import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { sampleResult } from "../test/fixtures";
import TimeSeriesPanel from "./TimeSeriesPanel";

vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: { title: string }[] }) => <div data-testid="ts-charts">{charts.map((c) => c.title).join(", ")}</div>,
}));

describe("TimeSeriesPanel", () => {
  it("shows each series' summary, facts and charts", async () => {
    render(<TimeSeriesPanel series={sampleResult().time_series} />);

    expect(screen.getByRole("heading", { name: /sales over date/ })).toBeInTheDocument();
    expect(screen.getAllByText("12 monthly")).toHaveLength(2);
    expect(screen.getAllByText("too few periods")).toHaveLength(2);
    expect((await screen.findAllByTestId("ts-charts"))[0]).toHaveTextContent("sales: history and forecast");
  });

  it("explains an empty section", () => {
    render(<TimeSeriesPanel series={[]} />);
    expect(screen.getByText(/no date column with enough dates/)).toBeInTheDocument();
  });
});
