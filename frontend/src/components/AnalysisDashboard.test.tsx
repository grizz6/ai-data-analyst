import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sampleResult } from "../test/fixtures";
import AnalysisDashboard from "./AnalysisDashboard";

// Plotly needs a real canvas and layout engine; the chart grid has nothing to test here.
vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: unknown[] }) => <div data-testid="chart-grid">{charts.length} charts</div>,
}));

async function openTab(name: string) {
  await userEvent.click(screen.getByRole("tab", { name }));
  return screen.getByRole("tabpanel");
}

function story() {
  return screen.getByLabelText("What this dataset tells you");
}

describe("AnalysisDashboard", () => {
  // The open tab is kept in the address; start each test on the overview.
  afterEach(() => window.history.replaceState(null, "", "#"));

  it("opens with the dataset's story and labels who wrote it", () => {
    const result = sampleResult;
    render(<AnalysisDashboard result={result()} />);

    expect(within(story()).getByText("Rule-based summary, built from the computed results.")).toBeInTheDocument();
    expect(within(story()).getByText(result().explanation.dataset_overview)).toBeInTheDocument();
  });

  it("names the model when a language model wrote the summary", () => {
    const result = sampleResult();
    result.explanation = { ...result.explanation, configured: true, source: "llm", model: "llama-3.3-70b-versatile" };

    render(<AnalysisDashboard result={result} />);

    expect(within(story()).getByText(/^Written by llama-3\.3-70b-versatile/)).toBeInTheDocument();
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
    const overview = screen.getByRole("tabpanel");
    const sales = within(within(overview).getByRole("table", { name: "Numeric statistics" })).getByText("sales");
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
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Overview",
      "Data quality",
      "Variables",
      "Relationships",
      "Over time",
      "Next steps",
      "Data",
    ]);
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Variables" })).toHaveFocus();
    expect(screen.getByRole("tab", { name: "Variables" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows a time series tab only when the file has one", () => {
    render(<AnalysisDashboard result={sampleResult({ time_series: [] })} />);
    expect(screen.queryByRole("tab", { name: "Time series" })).not.toBeInTheDocument();
  });

  it("shows each correlation with its sample size and p-value", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const relationships = await openTab("Relationships");
    expect(within(relationships).getByText(/^Strongest link: sales ↔ units \(r = 0\.98\)/)).toBeInTheDocument();
    expect(within(within(relationships).getByRole("list", { name: "Correlations" })).getByText(/n = 31, p < 0.001/)).toBeInTheDocument();
  });

  it("links every download to this session", () => {
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
    expect(screen.getByRole("link", { name: "Data dictionary" })).toHaveAttribute(
      "href",
      `/api/sessions/${result.session_id}/dictionary.csv`,
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
    // The overview shows its own charts and every column at a glance.
    const atAGlance = result.visuals.overview.length + result.visuals.explore.length;
    expect(await screen.findByTestId("chart-grid")).toHaveTextContent(`${atAGlance} charts`);
    await openTab("Relationships");
    expect((await screen.findAllByTestId("chart-grid"))[0]).toHaveTextContent(`${result.visuals.relationships.length} charts`);
  });

  it("links each tab to its panel", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    for (const tab of screen.getAllByRole("tab")) {
      await userEvent.click(tab);
      expect(document.getElementById(tab.getAttribute("aria-controls")!)).toBeVisible();
    }
  });

  it("lists next steps with what to check first, linking back to the exploration", async () => {
    const result = sampleResult();
    render(<AnalysisDashboard result={result} />);
    const next = await openTab("Next steps");
    const list = within(next).getByRole("region", { name: "What this data could be used for" });
    const first = result.recommendations[0];
    expect(within(list).getByText(first.why)).toBeInTheDocument();
    await userEvent.click(within(list).getAllByRole("button", { name: first.action.label })[0]);
    expect(screen.getByRole("tab", { selected: true })).not.toHaveTextContent("Next steps");
  });

  it("shows duplicates and missing-value patterns on the quality tab", async () => {
    const result = sampleResult({
      duplicates: { count: 2, share: 1.5, groups: [{ rows: [1, 40], values: { region: "West" } }] },
      missing_dependencies: [
        {
          column: "units",
          missing: 4,
          missing_share: 12.9,
          related: [
            { column: "region", kind: "category", effect: 0.4, effect_name: "Cramér's V", p_value: 0.01, detail: "units is missing in 40% of 'East' rows vs 13% overall" },
          ],
        },
      ],
    });
    render(<AnalysisDashboard result={result} />);
    const quality = await openTab("Data quality");
    expect(within(within(quality).getByRole("table", { name: "Duplicate groups" })).getByText("1, 40")).toBeInTheDocument();
    expect(within(quality).getByText(/40% of 'East' rows vs 13% overall/)).toBeInTheDocument();
  });

  it("explores any number by any category, and any two categories together", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const relationships = await openTab("Relationships");
    const byGroup = within(relationships).getByRole("region", { name: "A number by group" });
    await userEvent.selectOptions(within(byGroup).getByLabelText("Group by"), "region");
    await userEvent.selectOptions(within(byGroup).getByLabelText("Number"), "units");
    expect(within(byGroup).getByText(/^region explains .*% of units/)).toBeInTheDocument();
    const pair = within(relationships).getByRole("region", { name: "Two categories together" });
    expect(within(pair).getByText(/^Cramér's V/)).toBeInTheDocument();
  });

  it("opens a column's card from the Variables tab", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const variables = await openTab("Variables");
    await userEvent.click(within(variables).getByRole("button", { name: /^units/ }));
    expect(within(variables).getByRole("article", { name: "Variable units" })).toBeInTheDocument();
  });
});
