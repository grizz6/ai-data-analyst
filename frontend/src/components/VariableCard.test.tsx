import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { VariableProfile } from "../types";
import VariableCard from "./VariableCard";

vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: { id: string }[] }) => <div data-testid="charts">{charts.map((c) => c.id).join(" ")}</div>,
}));

const box = { n: 100, q1: 30, median: 40, q3: 50, low: 10, high: 70, mean: 46 };

function numberVariable(): VariableProfile {
  return {
    name: "age",
    kind: "number",
    count: 100,
    missing: 0,
    missing_share: 0,
    distinct: 60,
    mean: 46,
    median: 40,
    std: 12,
    min: -4,
    max: 4100,
    skewness: 9.5,
    box,
    view: [0, 70],
    beyond_view: 1,
    histogram: { edges: [0, 10, 20], counts: [40, 60] },
    density: { x: [0, 10, 20], y: [0.1, 0.3, 0.1] },
    qq: { x: [-1, 0, 1], y: [30, 40, 50] },
    timeline: null,
    timeline_label: null,
    categories: [],
    binary: null,
    outliers: {
      iqr_low: 0,
      iqr_high: 80,
      iqr_count: 2,
      iqr_share: 2,
      z_threshold: 3,
      z_count: 1,
      z_share: 1,
      mean_all: 46,
      mean_without: 40.2,
      median_all: 40,
      median_without: 40,
      std_all: 12,
      std_without: 8,
      correlation: { column: "tenure", r_all: 0.1, r_without: 0.45 },
      rows: [
        { row: 31, value: 4100, z: 9.9, rules: ["IQR", "z"], cause: "About 100x the median: possibly a unit mix-up.", label: "C-31" },
        { row: 18, value: -4, z: -1.2, rules: ["IQR"], cause: "Negative in a column that is otherwise never negative.", label: "C-18" },
      ],
    },
    splits: [{ binary_column: "churned", groups: [{ label: "churned = Yes", box }, { label: "churned = No", box }], p_value: 0.5, effect: 0.01 }],
    compared: [],
    flags: ["Strongly right-skewed (skewness 9.5): the median is the better typical value."],
  };
}

describe("VariableCard", () => {
  it("shows a number's outliers under both rules, with and without them, and their likely causes", async () => {
    render(<VariableCard variable={numberVariable()} />);

    expect(screen.getByText(/^median 40 · range -4 to 4,100 · 2 outliers \(2%\)$/)).toBeInTheDocument();
    const rules = screen.getByRole("table", { name: "Outlier rules" });
    expect(within(rules).getByText("below 0 or above 80")).toBeInTheDocument();
    const shift = screen.getByRole("table", { name: "With and without outliers" });
    expect(within(within(shift).getByText("r with tenure").closest("tr")!).getByText("0.450")).toBeInTheDocument();
    const extremes = screen.getByRole("table", { name: "Most extreme values" });
    expect(within(extremes).getByText("C-31")).toBeInTheDocument();
    expect(within(extremes).getByText(/unit mix-up/)).toBeInTheDocument();
    expect(await screen.findByTestId("charts")).toHaveTextContent("histogram box violin qq split-churned");
    expect(screen.getByText(/Zoomed to 0 – 70: 1 far-out value/)).toBeInTheDocument();
  });

  it("ranks what differs between a yes/no column's groups", () => {
    const churned: VariableProfile = {
      ...numberVariable(),
      name: "churned",
      kind: "binary",
      distinct: 2,
      mean: null,
      median: null,
      outliers: null,
      splits: [],
      flags: [],
      binary: { values: ["No", "Yes"], counts: [65, 35], positive: "Yes", positive_share: 35 },
      compared: [
        { column: "tenure", kind: "numeric", effect: -0.64, effect_name: "rank-biserial", p_value: 0.0001, detail: "median 15 vs 38" },
        { column: "plan", kind: "category", effect: 0.02, effect_name: "Cramér's V", p_value: 0.9, detail: "" },
      ],
    };
    render(<VariableCard variable={churned} />);

    expect(screen.getByText("65% No / 35% Yes · differs most by tenure")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Compared against churned" });
    expect(within(within(table).getByText("tenure").closest("tr")!).getByText("likely real")).toBeInTheDocument();
    expect(within(within(table).getByText("plan").closest("tr")!).getByText("could be chance")).toBeInTheDocument();
  });
});
