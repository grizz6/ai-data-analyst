import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { loadRecent, rememberAnalysis } from "./recent";
import { jsonResponse, sampleResult } from "./test/fixtures";

vi.mock("./components/ChartGrid", () => ({ default: () => <div /> }));

const entry = (sessionId: string) => ({ sessionId, filename: "old.csv", rows: 12, columns: 3, openedAt: Date.now() });

describe("App", () => {
  beforeEach(() => localStorage.clear());

  it("remembers an analysis and reopens it from the upload screen", async () => {
    const result = sampleResult();
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(url === "/api/health" ? jsonResponse({ max_upload_mb: 10 }) : jsonResponse(result)),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File(["a,b\n1,2\n"], "sales_sample.csv"));
    expect(await screen.findByRole("heading", { level: 1, name: "sales_sample.csv" })).toBeInTheDocument();
    expect(loadRecent()[0]).toMatchObject({ sessionId: result.session_id, rows: 31, columns: 5 });

    await userEvent.click(screen.getByRole("button", { name: "New analysis" }));
    await userEvent.click(screen.getByRole("button", { name: /sales_sample\.csv/ }));

    expect(await screen.findByRole("heading", { level: 1, name: "sales_sample.csv" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(`/api/sessions/${result.session_id}`);
  });

  it("drops an expired analysis from the list and says why", async () => {
    rememberAnalysis(entry("gone"));
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        Promise.resolve(
          url === "/api/health"
            ? jsonResponse({ max_upload_mb: 10 })
            : jsonResponse({ detail: "This analysis wasn't found." }, 404),
        ),
      ),
    );
    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: /old\.csv/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This analysis wasn't found.");
    await waitFor(() => expect(screen.queryByRole("button", { name: /old\.csv/ })).not.toBeInTheDocument());
    expect(loadRecent()).toEqual([]);
  });

  it("keeps the five most recent, newest first, without duplicates", () => {
    for (const id of ["a", "b", "c", "d", "e", "f", "c"]) rememberAnalysis(entry(id));
    expect(loadRecent().map((r) => r.sessionId)).toEqual(["c", "f", "e", "d", "b"]);
  });
});
