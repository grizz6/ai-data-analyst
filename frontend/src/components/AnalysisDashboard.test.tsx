import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse, sampleResult } from "../test/fixtures";
import AnalysisDashboard from "./AnalysisDashboard";

// Plotly needs a real canvas and layout engine; the chart grid has nothing to test here.
vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: unknown[] }) => <div data-testid="chart-grid">{charts.length} charts</div>,
}));

function panel(heading: RegExp) {
  return screen.getByRole("heading", { name: heading }).closest(".panel") as HTMLElement;
}

describe("AnalysisDashboard", () => {
  it("labels a rule-based summary and says why", () => {
    render(<AnalysisDashboard result={sampleResult()} />);

    expect(screen.getByRole("heading", { name: "Summary (rule-based)" })).toBeInTheDocument();
    expect(screen.getByText(/no LLM API key is set on the server/)).toBeInTheDocument();
  });

  it("names the model when a language model wrote the summary", () => {
    const result = sampleResult();
    result.explanation = { ...result.explanation, configured: true, source: "llm", model: "llama-3.3-70b-versatile" };

    render(<AnalysisDashboard result={result} />);

    expect(screen.getByRole("heading", { name: "Summary (written by llama-3.3-70b-versatile)" })).toBeInTheDocument();
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

  it("shows each correlation with its sample size and p-value", () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    expect(within(panel(/Correlations/)).getByText(/n = 31, p < 0.001/)).toBeInTheDocument();
  });

  it("links both downloads to this session", () => {
    const result = sampleResult();
    render(<AnalysisDashboard result={result} />);

    expect(screen.getByRole("link", { name: "Download HTML report" })).toHaveAttribute(
      "href",
      `/api/sessions/${result.session_id}/report`,
    );
    expect(screen.getByRole("link", { name: "Download cleaned data (CSV)" })).toHaveAttribute(
      "href",
      `/api/sessions/${result.session_id}/cleaned.csv`,
    );
  });

  it("opens the print-ready report in a new tab for saving as PDF", () => {
    const result = sampleResult();
    render(<AnalysisDashboard result={result} />);

    const link = screen.getByRole("link", { name: "Save report as PDF" });
    expect(link).toHaveAttribute("href", `/api/sessions/${result.session_id}/report?print=true`);
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("badges identifier columns in the profile table", () => {
    const result = sampleResult();
    result.columns = result.columns.map((c) => (c.name === "region" ? { ...c, is_identifier: true } : c));

    render(<AnalysisDashboard result={result} />);

    const row = within(panel(/Column profiles/)).getByText("region").closest("tr") as HTMLElement;
    expect(within(row).getByText("identifier")).toBeInTheDocument();
  });

  it("loads the charts lazily", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    expect(await screen.findByTestId("chart-grid")).toHaveTextContent("2 charts");
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

    const chip = screen.getByRole("button", { name: "Which region has the highest sales?" });
    expect(screen.getByRole("button", { name: "How are sales and units related?" })).toBeInTheDocument();
    await userEvent.click(chip);

    expect(await screen.findByText("West.")).toBeInTheDocument();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ question: "Which region has the highest sales?" });
    // Once asked, a suggestion is no longer offered.
    expect(screen.queryByRole("button", { name: "Which region has the highest sales?" })).not.toBeInTheDocument();
  });

  it("links each section from the jump bar", () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const nav = screen.getByRole("navigation", { name: "Jump to section" });
    for (const link of within(nav).getAllByRole("link")) {
      const id = link.getAttribute("href")!.slice(1);
      expect(document.getElementById(id)).not.toBeNull();
    }
  });

  it("shows the server's message when the session has expired", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "This analysis wasn't found." }, 404)));
    render(<AnalysisDashboard result={sampleResult()} />);

    await userEvent.type(screen.getByPlaceholderText(/Which region/), "Anything?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("This analysis wasn't found.")).toBeInTheDocument();
  });
});
