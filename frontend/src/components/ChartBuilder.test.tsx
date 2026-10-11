import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse, sampleResult } from "../test/fixtures";
import ChartBuilder from "./ChartBuilder";

vi.mock("./ChartGrid", () => ({
  default: ({ charts }: { charts: { title: string }[] }) => (
    <ul data-testid="built-charts">
      {charts.map((c) => (
        <li key={c.title}>{c.title}</li>
      ))}
    </ul>
  ),
}));

const spec = (title: string, id = title) => ({ id, title, chart_type: "bar", plotly_json: { data: [] } });

function renderBuilder() {
  const result = sampleResult();
  render(<ChartBuilder sessionId={result.session_id} columns={result.columns} />);
  return result;
}

describe("ChartBuilder", () => {
  it("offers only columns that fit each slot", async () => {
    renderBuilder();

    const category = screen.getByLabelText("Category");
    expect([...category.querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "Choose…",
      "region",
      "product",
    ]);
    expect([...screen.getByLabelText("Value").querySelectorAll("option")].map((o) => o.textContent)).toEqual([
      "Number of rows",
      "sales",
      "units",
    ]);

    await userEvent.selectOptions(screen.getByLabelText("Chart type"), "line");
    expect(screen.getByLabelText("X axis")).toHaveTextContent("date");
  });

  it("sends the chosen columns and aggregate, then shows the chart", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(spec("Total sales by region")));
    vi.stubGlobal("fetch", fetchMock);
    const result = renderBuilder();

    const build = screen.getByRole("button", { name: "Build chart" });
    expect(build).toBeDisabled();
    await userEvent.selectOptions(screen.getByLabelText("Category"), "region");
    await userEvent.selectOptions(screen.getByLabelText("Value"), "sales");
    await userEvent.selectOptions(screen.getByLabelText("Combine as"), "sum");
    await userEvent.click(build);

    expect(await screen.findByText("Total sales by region")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/sessions/${result.session_id}/charts`);
    expect(JSON.parse(init.body)).toEqual({ chart_type: "bar", x: "region", y: "sales", aggregate: "sum" });
  });

  it("counts rows when no value column is chosen", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(spec("Count by product")));
    vi.stubGlobal("fetch", fetchMock);
    renderBuilder();

    await userEvent.selectOptions(screen.getByLabelText("Category"), "product");
    expect(screen.queryByLabelText("Combine as")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Build chart" }));

    await screen.findByText("Count by product");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ y: null, aggregate: "count" });
  });

  it("shows the server's reason when a chart can't be built", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "'units' has no values to chart." }, 400)));
    renderBuilder();

    await userEvent.selectOptions(screen.getByLabelText("Chart type"), "histogram");
    await userEvent.selectOptions(screen.getByLabelText("Column"), "units");
    await userEvent.click(screen.getByRole("button", { name: "Build chart" }));

    expect(await screen.findByText("'units' has no values to chart.")).toBeInTheDocument();
  });

  it("leaves identifier columns out", () => {
    const result = sampleResult();
    const columns = result.columns.map((c) => (c.name === "region" ? { ...c, is_identifier: true } : c));
    render(<ChartBuilder sessionId={result.session_id} columns={columns} />);

    expect(screen.getByLabelText("Category")).not.toHaveTextContent("region");
  });
});
