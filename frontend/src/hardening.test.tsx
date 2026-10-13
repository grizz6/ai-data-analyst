import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { cleanedCsvUrl, dictionaryUrl, planForGoal, printableReportUrl, reportDownloadUrl, uploadDataset } from "./api";
import AnalysisDashboard from "./components/AnalysisDashboard";
import { loadRecent, rememberAnalysis } from "./recent";
import { jsonResponse, sampleResult } from "./test/fixtures";

vi.mock("./components/ChartGrid", () => ({ default: () => <div /> }));

const XSS = '<img src=x onerror="window.__pwned=1">';

function hostile() {
  const result = sampleResult({ filename: `${XSS}.csv` });
  result.explanation = {
    ...result.explanation,
    dataset_overview: `Overview ${XSS}`,
    analysis_summary: "<script>window.__pwned=1</script>",
    recommendations: [XSS],
  };
  result.columns = result.columns.map((c, i) => (i === 0 ? { ...c, name: XSS } : c));
  result.variables = result.variables.map((v, i) => (i === 0 ? { ...v, name: XSS, flags: [XSS] } : v));
  result.quality_issues = [{ severity: "warning", category: "x", message: XSS, details: {}, column: null }];
  result.preview_rows = [{ [XSS]: XSS }];
  result.cleaned_preview_rows = [{ [XSS]: XSS }];
  if (result.review) result.review = { ...result.review, verdict: XSS, concerns: [XSS] };
  return result;
}

function expectNoInjectedMarkup(container: HTMLElement) {
  expect(container.querySelector("img[src='x']")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
  expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
}

describe("untrusted text from a file or the model is shown as text, never run", () => {
  afterEach(() => window.history.replaceState(null, "", "#"));

  for (const tab of ["Overview", "Data quality", "Variables", "Relationships", "Next steps", "Data"]) {
    it(`on the ${tab} tab`, async () => {
      const { container } = render(<AnalysisDashboard result={hostile()} />);
      await userEvent.click(screen.getByRole("tab", { name: tab }));
      expectNoInjectedMarkup(container);
    });
  }

  it("shows the hostile file name literally", () => {
    render(<AnalysisDashboard result={hostile()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(`${XSS}.csv`);
  });

  it("in the recent analyses list", () => {
    localStorage.clear();
    rememberAnalysis({ sessionId: "s", filename: XSS, rows: 1, columns: 1, openedAt: Date.now() });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ max_upload_mb: 10 })));
    const { container } = render(<App />);
    expect(screen.getByRole("button", { name: new RegExp("onerror") })).toBeInTheDocument();
    expectNoInjectedMarkup(container);
  });
});

describe("the browser only talks to this site's own API", () => {
  it("every request goes to a relative /api path", async () => {
    const fetchMock = vi.fn<(url: string) => Promise<Response>>(() => Promise.resolve(jsonResponse(sampleResult())));
    vi.stubGlobal("fetch", fetchMock);
    await uploadDataset(new File(["a\n1\n"], "a.csv"));
    await planForGoal("abc", "goal");
    for (const [url] of fetchMock.mock.calls) {
      expect(url).toMatch(/^\/api\//);
    }
  });

  it("download links are relative and keep the session id out of other sites' logs", () => {
    for (const url of [reportDownloadUrl("s"), printableReportUrl("s"), dictionaryUrl("s"), cleanedCsvUrl("s")]) {
      expect(url.startsWith("/api/sessions/s/")).toBe(true);
    }
  });

  it("session ids are encoded only where the server expects them", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(sampleResult()));
    vi.stubGlobal("fetch", fetchMock);
    await uploadDataset(new File(["a"], "a.csv"), "../../etc?x=1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/upload?sheet=..%2F..%2Fetc%3Fx%3D1");
  });

  it("the page opened in a new tab can't reach back into the app", () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const pdf = screen.getByRole("link", { name: "Save as PDF" });
    expect(pdf).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(pdf).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("no source file mentions an API key, a model provider or a third-party host", () => {
    // Every source file of the app, as text (tests excluded).
    const sources = import.meta.glob(["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}"], {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;
    expect(Object.keys(sources).length).toBeGreaterThan(10);
    const offenders: string[] = [];
    for (const [path, text] of Object.entries(sources)) {
      for (const pattern of [/gsk_/, /api\.groq\.com/, /Bearer /, /https?:\/\/(?!localhost)[a-z0-9.-]+\.[a-z]{2,}/i]) {
        if (pattern.test(text)) offenders.push(`${path}: ${pattern}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("browser storage keeps nothing sensitive", () => {
  beforeEach(() => localStorage.clear());

  it("remembers only the id, name and size of an analysis, not its data", async () => {
    const result = sampleResult();
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => Promise.resolve(url === "/api/health" ? jsonResponse({ max_upload_mb: 10 }) : jsonResponse(result))),
    );
    render(<App />);
    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File(["a\n1\n"], "sales_sample.csv"));
    await screen.findByRole("heading", { level: 1, name: "sales_sample.csv" });
    const stored = JSON.stringify({ ...localStorage });
    expect(Object.keys(loadRecent()[0]).sort()).toEqual(["columns", "filename", "openedAt", "rows", "sessionId"]);
    const firstValue = String(Object.values(result.preview_rows[0])[0]);
    expect(stored).not.toContain(firstValue);
    expect(stored).not.toContain(result.explanation.dataset_overview.slice(0, 30));
  });

  it("survives corrupted storage", () => {
    localStorage.setItem("ada-recent", "{not json");
    localStorage.setItem("ada-theme", "<script>");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ max_upload_mb: 10 })));
    render(<App />);
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });
});

describe("uploads are checked before they are sent", () => {
  beforeEach(() => localStorage.clear());

  function setup() {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url === "/api/health"
          ? jsonResponse({ max_upload_mb: 1, max_csv_mb: 1, max_excel_mb: 1 })
          : jsonResponse(sampleResult()),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    return fetchMock;
  }

  const big = (name: string) => new File([new Uint8Array(2 * 1024 * 1024)], name);

  it("refuses a CSV over the limit without uploading it", async () => {
    const fetchMock = setup();
    await screen.findByText(/CSV up to 1 MB/);
    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), big("big.csv"));
    expect(await screen.findByRole("alert")).toHaveTextContent("1 MB");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/upload")).toBe(false);
  });

  it("refuses an Excel file over its own limit", async () => {
    const fetchMock = setup();
    await screen.findByText(/Excel up to 1 MB/);
    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), big("big.xlsx"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Excel files can be up to 1 MB");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/upload")).toBe(false);
  });
});

describe("server answers are shown plainly", () => {
  beforeEach(() => localStorage.clear());

  async function uploadAnswered(response: Response) {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => Promise.resolve(url === "/api/health" ? jsonResponse({ max_upload_mb: 10 }) : response)),
    );
    render(<App />);
    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File(["a\n1\n"], "a.csv"));
    return screen.findByRole("alert");
  }

  it("a rate limit says how long to wait", async () => {
    const alert = await uploadAnswered(jsonResponse({ detail: "Too many uploads: the limit is 10 per hour. Try again in 5 minutes." }, 429));
    expect(alert).toHaveTextContent("Try again in 5 minutes");
  });

  it("a server error shows only its reference", async () => {
    const alert = await uploadAnswered(jsonResponse({ detail: "Analysis failed because of a server error. Reference: ab12cd34." }, 500));
    expect(alert).toHaveTextContent("Reference: ab12cd34");
  });

  it("an HTML error page from the host is not dumped on screen", async () => {
    const alert = await uploadAnswered(new Response("<html><body>Bad gateway</body></html>", { status: 502 }));
    expect(alert).not.toHaveTextContent("<html>");
    expect(alert).toHaveTextContent("waking up or busy");
  });

  it("a validation error list is not dumped on screen", async () => {
    const alert = await uploadAnswered(jsonResponse({ detail: [{ loc: ["body", "file"], msg: "Field required" }] }, 422));
    expect(alert).toHaveTextContent("Upload failed");
  });

  it("the upload screen works again after an error", async () => {
    await uploadAnswered(jsonResponse({ detail: "The file is empty." }, 400));
    expect(screen.getByRole("button", { name: "Choose file" })).toBeEnabled();
  });
});

describe("keyboard use", () => {
  afterEach(() => window.history.replaceState(null, "", "#"));

  it("arrow keys move between tabs", async () => {
    render(<AnalysisDashboard result={sampleResult()} />);
    const tabs = screen.getByRole("tablist");
    within(tabs).getByRole("tab", { name: "Overview" }).focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(within(tabs).getByRole("tab", { name: "Data quality" })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(within(tabs).getByRole("tab", { name: "Data" })).toHaveAttribute("aria-selected", "true");
  });

  it("an unknown tab in the address falls back to the overview", () => {
    window.history.replaceState(null, "", "#<script>");
    render(<AnalysisDashboard result={sampleResult()} />);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  });
});
