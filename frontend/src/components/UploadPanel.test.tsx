import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as compress from "../compress";
import { jsonResponse } from "../test/fixtures";
import UploadPanel from "./UploadPanel";

const MB = 1024 * 1024;

function renderPanel(csvLimitMb = 1, excelLimitMb = 1, uploadLimitMb = csvLimitMb) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      jsonResponse({ max_upload_mb: uploadLimitMb, max_csv_mb: csvLimitMb, max_excel_mb: excelLimitMb }),
    ),
  );
  const onUpload = vi.fn();
  const onReject = vi.fn();
  render(<UploadPanel onUpload={onUpload} onReject={onReject} loading={false} />);
  return { onUpload, onReject };
}

describe("UploadPanel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the upload limits the server reports", async () => {
    renderPanel(3, 2);
    expect(await screen.findByText(/CSV up to 3 MB, Excel up to 2 MB/)).toBeInTheDocument();
  });

  it("holds Excel files to their own, lower limit", async () => {
    const { onUpload, onReject } = renderPanel(3, 1);
    await screen.findByText(/CSV up to 3 MB/);
    const workbook = new File([new Uint8Array(MB + 1)], "book.xlsx");

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), workbook);

    await waitFor(() => expect(onReject).toHaveBeenCalledWith(expect.stringMatching(/^Excel files can be up to 1 MB/)));
    expect(onUpload).not.toHaveBeenCalled();
  });

  it("uploads a file that fits under the limit", async () => {
    const { onUpload, onReject } = renderPanel(1);
    await screen.findByText(/CSV up to 1 MB/);
    const file = new File(["a,b\n1,2\n"], "small.csv", { type: "text/csv" });

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), file);

    expect(onUpload).toHaveBeenCalledWith(file);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("refuses a CSV over its limit before sending it", async () => {
    const { onUpload, onReject } = renderPanel(1);
    await screen.findByText(/CSV up to 1 MB/);
    const big = new File([new Uint8Array(MB + 1)], "big.csv", { type: "text/csv" });

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), big);

    await waitFor(() => expect(onReject).toHaveBeenCalledWith(expect.stringMatching(/^CSV files can be up to 1 MB/)));
    expect(onUpload).not.toHaveBeenCalled();
  });

  it("compresses a large CSV and uploads the smaller file", async () => {
    vi.spyOn(compress, "canCompress").mockReturnValue(true);
    const gz = new File([new Uint8Array(10)], "big.csv.gz");
    const gzip = vi.spyOn(compress, "gzipFile").mockResolvedValue(gz);
    const { onUpload, onReject } = renderPanel(10, 1, 1);
    await screen.findByText(/CSV up to 10 MB/);
    const big = new File([new Uint8Array(3 * MB)], "big.csv");

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), big);

    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(gz));
    expect(gzip).toHaveBeenCalledWith(big);
    expect(onReject).not.toHaveBeenCalled();
  });

  it("leaves small CSVs and Excel files uncompressed", async () => {
    vi.spyOn(compress, "canCompress").mockReturnValue(true);
    const gzip = vi.spyOn(compress, "gzipFile");
    const { onUpload } = renderPanel(10, 10, 10);
    await screen.findByText(/CSV up to 10 MB/);
    const book = new File([new Uint8Array(2 * MB)], "book.xlsx");

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), book);
    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File(["a\n1\n"], "tiny.csv"));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(2));
    expect(gzip).not.toHaveBeenCalled();
  });

  it("refuses a file still over the upload cap after compression", async () => {
    vi.spyOn(compress, "canCompress").mockReturnValue(true);
    vi.spyOn(compress, "gzipFile").mockResolvedValue(new File([new Uint8Array(2 * MB)], "big.csv.gz"));
    const { onUpload, onReject } = renderPanel(10, 1, 1);
    await screen.findByText(/CSV up to 10 MB/);

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File([new Uint8Array(5 * MB)], "big.csv"));

    await waitFor(() => expect(onReject).toHaveBeenCalledWith(expect.stringMatching(/^Even compressed/)));
    expect(onUpload).not.toHaveBeenCalled();
  });

  it("sends the original file if compression fails", async () => {
    vi.spyOn(compress, "canCompress").mockReturnValue(true);
    vi.spyOn(compress, "gzipFile").mockRejectedValue(new Error("no"));
    const { onUpload } = renderPanel(10, 1, 10);
    await screen.findByText(/CSV up to 10 MB/);
    const big = new File([new Uint8Array(2 * MB)], "big.csv");

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), big);

    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(big));
  });

  it("explains the lower limit in a browser that can't compress", async () => {
    vi.spyOn(compress, "canCompress").mockReturnValue(false);
    const { onUpload, onReject } = renderPanel(10, 1, 1);
    await screen.findByText(/CSV up to 10 MB/);

    await userEvent.upload(screen.getByLabelText("CSV or Excel file"), new File([new Uint8Array(2 * MB)], "big.csv"));

    await waitFor(() => expect(onReject).toHaveBeenCalledWith(expect.stringMatching(/can't compress/)));
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
