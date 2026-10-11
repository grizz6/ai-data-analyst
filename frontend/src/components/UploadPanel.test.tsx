import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse } from "../test/fixtures";
import UploadPanel from "./UploadPanel";

const MB = 1024 * 1024;

function renderPanel(serverLimitMb = 1) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ max_upload_mb: serverLimitMb })));
  const onUpload = vi.fn();
  const onReject = vi.fn();
  render(<UploadPanel onUpload={onUpload} onReject={onReject} loading={false} />);
  return { onUpload, onReject };
}

describe("UploadPanel", () => {
  it("shows the upload limit the server reports", async () => {
    renderPanel(3);
    expect(await screen.findByText(/Max 3 MB/)).toBeInTheDocument();
  });

  it("uploads a file that fits under the limit", async () => {
    const { onUpload, onReject } = renderPanel(1);
    await screen.findByText(/Max 1 MB/);
    const file = new File(["a,b\n1,2\n"], "small.csv", { type: "text/csv" });

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), file);

    expect(onUpload).toHaveBeenCalledWith(file);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("refuses an oversized file before sending it", async () => {
    const { onUpload, onReject } = renderPanel(1);
    await screen.findByText(/Max 1 MB/);
    const big = new File([new Uint8Array(MB + 1)], "big.csv", { type: "text/csv" });

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), big);

    await waitFor(() => expect(onReject).toHaveBeenCalledWith("File exceeds the 1 MB upload limit."));
    expect(onUpload).not.toHaveBeenCalled();
  });

  it("uploads the sample file on request", async () => {
    const { onUpload } = renderPanel();
    vi.mocked(fetch).mockResolvedValueOnce(new Response("date,region,product,sales,units\n2024-01-05,West,A,1,2\n"));
    await userEvent.click(screen.getByRole("button", { name: /Try the sample sales data/ }));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    const file: File = onUpload.mock.calls[0][0];
    expect(file.name).toBe("sales_sample.csv");
    expect(vi.mocked(fetch)).toHaveBeenLastCalledWith("/api/sample.csv");
    expect(await file.text()).toMatch(/^date,region,product,sales,units/);
  });

  it("says so when the sample can't be fetched", async () => {
    const { onUpload, onReject } = renderPanel();
    vi.mocked(fetch).mockResolvedValueOnce(new Response("", { status: 404 }));
    await userEvent.click(screen.getByRole("button", { name: /Try the sample sales data/ }));

    await waitFor(() => expect(onReject).toHaveBeenCalledWith(expect.stringMatching(/sample file couldn't be loaded/)));
    expect(onUpload).not.toHaveBeenCalled();
  });
});
