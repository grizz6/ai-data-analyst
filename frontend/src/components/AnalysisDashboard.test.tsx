import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, sampleResult } from "../test/fixtures";
import AnalysisDashboard from "./AnalysisDashboard";

// The Models panel trains on load and is tested on its own.
vi.mock("./MachineLearningPanel", () => ({
  default: ({ request }: { request: { target: string } | null }) => (
    <div data-testid="ml-panel">{request ? `training ${request.target}` : ""}</div>
  ),
}));
// Plotly needs a real canvas and layout engine; the chart grid has nothing to test here.
vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: unknown[] }) => <div data-testid="chart-grid">{charts.length} charts</div>,
}));

async function openTab(name: string) {
  await userEvent.click(screen.getByRole("tab", { name }));
  return screen.getByRole("tabpanel");
}

function summary() {
  return screen.getByText("Summary and key findings").closest("details") as HTMLElement;
}

describe("AnalysisDashboard", () => {
  // The open tab is kept in the address; start each test on the overview.
  afterEach(() => window.history.replaceState(null, "", "#"));

  it("labels a rule-based summary and says why", () => {
    render(<AnalysisDashboard result={sampleResult()} />);

    expect(within(summary()).getByText(/^Rule-based summary\. Set an LLM API key/)).toBeInTheDocument();
  });

  it("names the model when a language model wrote the summary", () => {
    const result = sampleResult();
    result.explanation = { ...result.explanation, configured: true, source: "llm", model: "llama-3.3-70b-versatile" };

    render(<AnalysisDashboard result={result} />);

    expect(within(summary()).getByText(/^Written by llama-3\.3-70b-versatile/)).toBeInTheDocument();
  });

  it("explains a fallback when the model's text was rejected", () => {
    const result = sampleResult();
    result.explanation = {
      ...result.explanation,
      configured: true,
      fallback_reason: "model wrote numbers not in the analysis: 37",
    };

    render(<AnalysisDashboard result={result} />);

    expect(screen.getByText(/model wrote numbers not in the analysis: 37/)).toBeInTheDocument();
  });

  it("shows the file name, size, and readable statistics", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);

    expect(screen.getByRole("heading", { level: 1, name: "sales_sample.csv" })).toBeInTheDocument();
    expect(screen.getByText(/31 rows · 5 columns/)).toBeInTheDocument();
    const explore = await openTab("Explore");
    const sales = within(within(explore).getByRole("table", { name: "Numeric statistics" })).getByText("sales");
    expect(within(sales.closest("tr") as HTMLElement).getByText("9,419.35")).toBeInTheDocument();
    const data = await openTab("Data");
    const date = within(within(data).getByRole("table", { name: "Column profiles" })).getByText("date");
    expect(within(date.closest("tr") as HTMLElement).getByText("Date")).toBeInTheDocument();
  });

  it("says when a large file was analyzed on a sample", () => {
    render(<AnalysisDashboard result={sampleResult({ row_count: 100_000, rows_in_file: 694_646, sampled: true })} />);
    expect(screen.getByText(/Sample of 100,000 of 694,646 rows/)).toBeInTheDocument();
  });

  it("opens on the overview with a one-line takeaway and number tiles", () => {
    render(<AnalysisDashboard result={sampleResult()} />);

    const overview = screen.getByRole("tabpanel");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(within(overview).getByText(/^31 rows × 5 columns · .*% of cells filled$/)).toBeInTheDocument();
    expect(within(overview).getByText("Rows").nextSibling).toHaveTextContent("31");
  });

  it("switches tabs by click and with the arrow keys, and remembers the tab in the address", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);

    await openTab("Data quality");
    expect(window.location.hash).toBe("#quality");
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Variables" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Variables" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows a time series tab only when the file has one", () => {
    render(<AnalysisDashboard result={sampleResult({ time_series: [] })} />);
    expect(screen.queryByRole("tab", { name: "Time series" })).not.toBeInTheDocument();
  });

  it("starts training models in the background before the Models tab is opened", () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    expect(screen.getByTestId("ml-panel")).not.toBeVisible();
  });

  it("sends a question with Enter, but Shift+Enter starts a new line", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ answer: "Ok.", configured: false, source: "rule_based", model: null, fallback_reason: null }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AnalysisDashboard result={sampleResult()} />);
    await openTab("Ask");

    const box = screen.getByRole("textbox", { name: "Your question" });
    await userEvent.type(box, "First line{Shift>}{Enter}{/Shift}second");
    expect(fetchMock).not.toHaveBeenCalled();
    await userEvent.type(box, "{Enter}");

    expect(await screen.findByText("Ok.")).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: "First line\nsecond" });
  });

  it("shows each correlation with its sample size and p-value", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const relationships = await openTab("Relationships");
    expect(within(relationships).getByText(/^Strongest link: sales ↔ units \(r = 0\.98\)/)).toBeInTheDocument();
    expect(within(within(relationships).getByRole("list", { name: "Correlations" })).getByText(/n = 31, p < 0.001/)).toBeInTheDocument();
  });

  it("links both downloads to this session", () => {
    const result = sampleResult();
    render(<AnalysisDashboard result={result} />);

    expect(screen.getByRole("link", { name: "Download report" })).toHaveAttribute(
      "href",
      `/api/sessions/${result.session_id}/report`,
    );
    expect(screen.getByRole("link", { name: "Cleaned CSV" })).toHaveAttribute(
      "href",
      `/api/sessions/${result.session_id}/cleaned.csv`,
    );
  });

  it("opens the print-ready report in a new tab for saving as PDF", () => {
    const result = sampleResult();
    render(<AnalysisDashboard result={result} />);

    const link = screen.getByRole("link", { name: "Save as PDF" });
    expect(link).toHaveAttribute("href", `/api/sessions/${result.session_id}/report?print=true`);
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("badges identifier columns in the profile table", async () => {
    const result = sampleResult();
    result.columns = result.columns.map((c) => (c.name === "region" ? { ...c, is_identifier: true } : c));

    render(<AnalysisDashboard result={result} />);

    const data = await openTab("Data");
    const profiles = within(data).getByRole("table", { name: "Column profiles" });
    const row = within(profiles).getByText("region").closest("tr") as HTMLElement;
    expect(within(row).getByText("identifier")).toBeInTheDocument();
  });

  it("loads each tab's charts lazily", async () => {
    const result = sampleResult();
    render(<AnalysisDashboard result={result} />);
    // The overview's own charts plus the automatic ones.
    expect(await screen.findByTestId("chart-grid")).toHaveTextContent(`${result.visuals.overview.length + 2} charts`);
    await openTab("Relationships");
    expect(await screen.findByTestId("chart-grid")).toHaveTextContent(`${result.visuals.relationships.length} charts`);
  });

  it("asks a question and shows the answer", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ answer: "West leads on sales.", configured: false, source: "rule_based", fallback_reason: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const result = sampleResult();
    render(<AnalysisDashboard result={result} />);
    await openTab("Ask");

    const ask = screen.getByRole("button", { name: "Ask" });
    expect(ask).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText(/Which region/), "Which region sells most?");
    await userEvent.click(ask);

    expect(await screen.findByText("West leads on sales.")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/sessions/${result.session_id}/ask`);
  });

  it("keeps the thread, clears the box, and shows earlier turns from the session", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          answer: "East is lowest.",
          configured: true,
          source: "llm",
          model: "test-model",
          fallback_reason: null,
        }),
      ),
    );
    const result = sampleResult({
      chat_history: [
        { question: "Which region sells most?", answer: "West.", source: "rule_based", model: null, fallback_reason: null },
      ],
    });
    render(<AnalysisDashboard result={result} />);
    await openTab("Ask");

    const thread = screen.getByRole("list", { name: "Questions and answers" });
    expect(within(thread).getByText("West.")).toBeInTheDocument();

    const box = screen.getByRole("textbox", { name: "Your question" });
    await userEvent.type(box, "And the least?{Control>}{Enter}{/Control}");

    expect(await within(thread).findByText("East is lowest.")).toBeInTheDocument();
    expect(within(thread).getByText("Written by test-model")).toBeInTheDocument();
    expect(within(thread).getAllByRole("listitem")).toHaveLength(2);
    expect(box).toHaveValue("");
  });

  it("offers questions built from the file's columns and asks one on click", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ answer: "West.", configured: false, source: "rule_based", model: null, fallback_reason: null }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AnalysisDashboard result={sampleResult()} />);
    await openTab("Ask");

    const chip = screen.getByRole("button", { name: "Which region has the highest sales?" });
    expect(screen.getByRole("button", { name: "How are sales and units related?" })).toBeInTheDocument();
    await userEvent.click(chip);

    expect(await screen.findByText("West.")).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: "Which region has the highest sales?" });
    // Once asked, a suggestion is no longer offered.
    expect(screen.queryByRole("button", { name: "Which region has the highest sales?" })).not.toBeInTheDocument();
  });

  it("links each tab to its panel", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    for (const tab of screen.getAllByRole("tab")) {
      await userEvent.click(tab);
      expect(document.getElementById(tab.getAttribute("aria-controls")!)).toBeVisible();
    }
  });

  it("shows the server's message when the session has expired", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "This analysis wasn't found." }, 404)));
    render(<AnalysisDashboard result={sampleResult()} />);
    await openTab("Ask");

    await userEvent.type(screen.getByPlaceholderText(/Which region/), "Anything?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("This analysis wasn't found.")).toBeInTheDocument();
  });

  it("runs a suggestion: training opens the Models tab on that target", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const suggestions = await openTab("Suggestions");
    const list = within(suggestions).getByRole("region", { name: "What to run next" });
    await userEvent.click(within(list).getByRole("button", { name: "Train models on sales" }));

    expect(screen.getByRole("tab", { name: "Models" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("ml-panel")).toHaveTextContent("training sales");
  });

  it("opens a column's card from the Variables tab", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const variables = await openTab("Variables");
    await userEvent.click(within(variables).getByRole("button", { name: /^units/ }));
    expect(within(variables).getByRole("article", { name: "Variable units" })).toBeInTheDocument();
  });
});
