import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { loadRecent, rememberAnalysis } from "./recent";
import { jsonResponse, sampleResult } from "./test/fixtures";

// The Models panel trains on load and is tested on its own.
vi.mock("./components/MachineLearningPanel", () => ({ default: () => <div data-testid="ml-panel" /> }));
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

describe("privacy controls", () => {
  beforeEach(() => localStorage.clear());

  it("deletes the analysis on the server, forgets it, and says so", async () => {
    const result = sampleResult();
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/health") return Promise.resolve(jsonResponse({ max_upload_mb: 10 }));
      if (init?.method === "DELETE") return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(jsonResponse(result));
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<App />);

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File(["a\n1\n"], "sales_sample.csv"));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));

    expect(await screen.findByText("The analysis was deleted from the server.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(`/api/sessions/${result.session_id}`, { method: "DELETE" });
    expect(loadRecent()).toEqual([]);
    expect(screen.queryByRole("heading", { name: "Recent analyses" })).not.toBeInTheDocument();
  });

  it("does nothing if the delete isn't confirmed", async () => {
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>((url) =>
      Promise.resolve(url === "/api/health" ? jsonResponse({ max_upload_mb: 10 }) : jsonResponse(sampleResult())),
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<App />);

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File(["a\n1\n"], "sales_sample.csv"));
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));

    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    expect(screen.getByRole("heading", { level: 1, name: "sales_sample.csv" })).toBeInTheDocument();
  });

  it("clears the recent list from this browser", async () => {
    rememberAnalysis(entry("a"));
    rememberAnalysis(entry("b"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ max_upload_mb: 10 })));
    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Clear list" }));

    expect(screen.queryByRole("heading", { name: "Recent analyses" })).not.toBeInTheDocument();
    expect(loadRecent()).toEqual([]);
  });
});
