import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse, sampleResult } from "../test/fixtures";
import MachineLearningPanel from "./MachineLearningPanel";

vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: { title: string }[] }) => <div data-testid="charts">{charts.map((c) => c.title).join(" | ")}</div>,
}));

const score = (name: string, family: string, cv: number, train: number, test: number, overfit = false) => ({
  name,
  family,
  cv_mean: cv,
  cv_std: 0.02,
  train_score: train,
  test_score: test,
  test_secondary: 100,
  test_auc: null,
  fit_seconds: 0.4,
  overfit,
});

const report = {
  target: "sales",
  task: "regression",
  primary_metric: "R²",
  secondary_metric: "MAE",
  rows_used: 31,
  train_rows: 24,
  test_rows: 7,
  features: ["region", "product", "units"],
  dropped_features: ["date"],
  folds: 3,
  scores: [
    score("Baseline (average)", "baseline", -0.2, 0, -0.15),
    score("Linear regression", "linear", 0.961, 0.996, 0.995),
    score("Decision tree", "tree", 0.6, 1.0, 0.7, true),
  ],
  best_model: "Linear regression",
  beats_baseline: true,
  best_test_metrics: { "R²": 0.9946, MAE: 232.52, RMSE: 322.03 },
  importances: [],
  charts: [{ id: "model_comparison", title: "Models compared (R²)", chart_type: "bar", plotly_json: {} }],
  notes: ["Not used as inputs: date."],
  summary: "Best for 'sales': Linear regression, test R² 0.99 vs -0.15 baseline.",
};

function renderPanel(autoTrain = false) {
  const result = sampleResult();
  render(
    <MachineLearningPanel
      sessionId={result.session_id}
      columns={result.columns}
      suggestions={result.model_targets}
      autoTrain={autoTrain}
    />,
  );
  return result;
}

describe("MachineLearningPanel", () => {
  it("trains the suggested target straight away and shows train, CV and test scores", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(report));
    vi.stubGlobal("fetch", fetchMock);
    const result = renderPanel(true);

    const results = await screen.findByLabelText("Model results");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ target: "sales" });
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/sessions/${result.session_id}/model`);
    const best = within(results).getByText("best").closest("tr") as HTMLElement;
    expect(within(best).getByText("0.995")).toBeInTheDocument(); // test score
    const tree = within(results).getByText("Decision tree").closest("tr") as HTMLElement;
    expect(within(tree).getByText("overfits")).toBeInTheDocument();
    expect(within(results).getByText("RMSE")).toBeInTheDocument();
    expect(await within(results).findByTestId("charts")).toHaveTextContent("Models compared (R²)");
  });

  it("lists suggested targets first, and trains another on request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ ...report, target: "region" }));
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();

    const select = screen.getByLabelText("Column to predict");
    expect(select.querySelectorAll("option")[1]).toHaveTextContent("sales (suggested)");
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.selectOptions(select, "region");
    await userEvent.click(screen.getByRole("button", { name: "Train and compare" }));
    await screen.findByLabelText("Model results");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ target: "region" });
  });

  it("shows the server's reason when a column can't be predicted", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "'region' needs at least two values with 5+ rows each." }, 400)));
    renderPanel();
    await userEvent.selectOptions(screen.getByLabelText("Column to predict"), "region");
    await userEvent.click(screen.getByRole("button", { name: "Train and compare" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("needs at least two values");
  });

  it("trains the target a suggestion asks for, and shows only the latest run", async () => {
    let finishFirst: (r: Response) => void = () => {};
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (finishFirst = resolve)))
      .mockResolvedValueOnce(jsonResponse({ ...report, target: "units", summary: "Best for 'units'." }));
    vi.stubGlobal("fetch", fetchMock);
    const result = sampleResult();
    render(
      <MachineLearningPanel
        sessionId={result.session_id}
        columns={result.columns}
        suggestions={result.model_targets}
        autoTrain
        request={{ target: "units", nonce: 1 }}
      />,
    );

    expect(await screen.findByText("Best for 'units'.")).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ target: "units" });
    // The auto-run on the suggested target finishes later and is ignored.
    finishFirst(jsonResponse(report));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(report.summary)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Column to predict")).toHaveValue("units");
  });
});

