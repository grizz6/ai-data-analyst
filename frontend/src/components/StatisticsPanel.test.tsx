import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { sampleResult } from "../test/fixtures";
import StatisticsPanel from "./StatisticsPanel";

describe("StatisticsPanel", () => {
  it("shows the group difference found in the sample file, with its verdict", () => {
    render(<StatisticsPanel tests={sampleResult().statistics} />);

    const table = screen.getByRole("heading", { name: "Do numbers differ between groups?" }).closest("section")!;
    const row = within(table).getAllByRole("row").find((r) => /sales.*product/s.test(r.textContent ?? ""))!;
    expect(within(row).getByText(/Product A/)).toBeInTheDocument();
    expect(within(row).getByText("likely real")).toBeInTheDocument();
  });

  it("explains rather than shows empty tables when nothing applies", () => {
    render(
      <StatisticsPanel
        tests={{
          distributions: [],
          rank_correlations: [],
          categorical_associations: [],
          group_differences: [],
          missing_patterns: [],
        }}
      />,
    );
    expect(screen.getByText(/doesn't have the numeric or category columns/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
