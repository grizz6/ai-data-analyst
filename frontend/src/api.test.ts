import { describe, expect, it, vi } from "vitest";
import { askQuestion, cleanedCsvUrl, reportDownloadUrl, uploadDataset } from "./api";
import { jsonResponse, sampleResult } from "./test/fixtures";

function stubFetch(response: Response) {
  const fetchMock = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const file = new File(["a,b\n1,2\n"], "data.csv", { type: "text/csv" });

describe("uploadDataset", () => {
  it("posts the file as multipart form data", async () => {
    const fetchMock = stubFetch(jsonResponse(sampleResult()));

    const result = await uploadDataset(file);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/upload");
    expect(init.method).toBe("POST");
    expect((init.body as FormData).get("file")).toBe(file);
    expect(result.filename).toBe("sales_sample.csv");
  });

  it("asks for a specific sheet, URL-encoded", async () => {
    const fetchMock = stubFetch(jsonResponse(sampleResult()));
    await uploadDataset(file, "Q3 & Q4");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/upload?sheet=Q3%20%26%20Q4");
  });

  it("surfaces the server's explanation when the upload is refused", async () => {
    stubFetch(jsonResponse({ detail: "File exceeds the 10 MB upload limit." }, 413));
    await expect(uploadDataset(file)).rejects.toThrow("File exceeds the 10 MB upload limit.");
  });
});

describe("askQuestion", () => {
  it("posts the question as JSON to the session", async () => {
    const fetchMock = stubFetch(
      jsonResponse({ answer: "West.", configured: false, source: "rule_based", fallback_reason: null }),
    );

    const response = await askQuestion("abc", "Top region?");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/sessions/abc/ask");
    expect(JSON.parse(init.body as string)).toEqual({ question: "Top region?" });
    expect(response.answer).toBe("West.");
  });

  it("explains an expired session", async () => {
    stubFetch(jsonResponse({ detail: "This analysis wasn't found." }, 404));
    await expect(askQuestion("gone", "Hi?")).rejects.toThrow("This analysis wasn't found.");
  });
});

describe("download URLs", () => {
  it("point at the session's report and cleaned CSV", () => {
    expect(reportDownloadUrl("abc")).toBe("/api/sessions/abc/report");
    expect(cleanedCsvUrl("abc")).toBe("/api/sessions/abc/cleaned.csv");
  });
});
