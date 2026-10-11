import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse, sampleResult } from "../test/fixtures";
import MachineLearningPanel from "./MachineLearningPanel";

vi.mock("./ChartGrid", () => ({ default: () => <div data-testid="cluster-chart" /> }));

const report = {
  target: "sales",
  task: "regression",
  primary_metric: "R²",
  secondary_metric: "mean absolute error",
  rows_used: 31,
  features: ["region", "product", "units"],
  dropped_features: ["date"],
  folds: 5,
  scores: [
    { name: "Baseline (average)", primary: -0.52, primary_std: 0.7, secondary: 2867.9 },
    { name: "Linear regression (ridge)", primary: 0.9876, primary_std: 0.0067, secondary: 264.3 },
  ],
  best_model: "Linear regression (ridge)",
  beats_baseline: true,
  importances: [
    { feature: "units", importance: 0.9 },
    { feature: "product", importance: 0.06 },
  ],
  notes: ["Left out as inputs: date."],
  summary: "'sales' can be predicted from the other columns.",
};

function renderPanel() {
  const result = sampleResult();
  render(<MachineLearningPanel sessionId={result.session_id} columns={result.columns} clustering={result.clustering} />);
  return result;
}

describe("MachineLearningPanel", () => {
  it("shows the groups found, with what makes each stand out", async () => {
    renderPanel();
    expect(screen.getByText(/fall into 3 groups/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Group \d$/)).toHaveLength(3);
    expect(await screen.findByTestId("cluster-chart")).toBeInTheDocument();
  });

  it("offers every non-identifier, non-date column as a target and shows the comparison", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(report));
    vi.stubGlobal("fetch", fetchMock);
    const result = renderPanel();

    const select = screen.getByLabelText("Column to predict");
    expect([...select.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "Choose…",
      "region",
      "product",
      "sales",
      "units",
    ]);
    await userEvent.selectOptions(select, "sales");
    await userEvent.click(screen.getByRole("button", { name: "Train and compare" }));

    const results = await screen.findByLabelText("Model results");
    expect(within(results).getByText("'sales' can be predicted from the other columns.")).toBeInTheDocument();
    const best = within(results).getByText("best").closest("tr") as HTMLElement;
    expect(within(best).getByText("0.988")).toBeInTheDocument();
    expect(within(results).getByText("units")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(`/api/sessions/${result.session_id}/model`, expect.objectContaining({ method: "POST" }));
  });

  it("shows the server's reason when a column can't be predicted", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "'region' needs at least two values with 5+ rows each." }, 400)));
    renderPanel();
    await userEvent.selectOptions(screen.getByLabelText("Column to predict"), "region");
    await userEvent.click(screen.getByRole("button", { name: "Train and compare" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("needs at least two values");
  });

  it("explains when there's nothing to group", () => {
    const result = sampleResult();
    render(<MachineLearningPanel sessionId="s" columns={result.columns} clustering={null} />);
    expect(screen.getByText(/needs at least two numeric columns and 50 rows/)).toBeInTheDocument();
  });
});
