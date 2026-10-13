import { useCallback, useEffect, useRef, useState } from "react";
import { sampleDataUrl } from "../api";
import { canCompress, COMPRESS_FROM_BYTES, gzipFile } from "../compress";

interface Props {
  onUpload: (file: File) => void;
  onReject: (message: string) => void;
  loading: boolean;
}

export default function UploadPanel({ onUpload, onReject, loading }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragover, setDragover] = useState(false);
  const [compressing, setCompressing] = useState(false);
  const [maxUploadMb, setMaxUploadMb] = useState(90);
  const [maxCsvMb, setMaxCsvMb] = useState(200);
  const [maxExcelMb, setMaxExcelMb] = useState(15);
  const busy = loading || compressing;

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((data: { max_upload_mb?: number; max_csv_mb?: number; max_excel_mb?: number }) => {
        if (data.max_upload_mb) setMaxUploadMb(data.max_upload_mb);
        if (data.max_csv_mb) setMaxCsvMb(data.max_csv_mb);
        if (data.max_excel_mb) setMaxExcelMb(data.max_excel_mb);
      })
      .catch(() => {});
  }, []);

  const handleFile = useCallback(
    async (file: File | undefined) => {
      if (!file || busy) return;
      // Same limits the server enforces; checking here saves sending a file that will be refused.
      const mb = (bytes: number) => bytes / 1024 / 1024;
      const isExcel = /\.xlsx?$/i.test(file.name);
      const isCsv = /\.csv$/i.test(file.name);
      if (isExcel && mb(file.size) > maxExcelMb) {
        onReject(`Excel files can be up to ${maxExcelMb} MB. Save the sheet as CSV (up to ${maxCsvMb} MB) instead.`);
        return;
      }
      if (isCsv && mb(file.size) > maxCsvMb) {
        onReject(`CSV files can be up to ${maxCsvMb} MB. Remove rows or columns you don't need, or split the file.`);
        return;
      }
      let toSend = file;
      if (isCsv && file.size >= COMPRESS_FROM_BYTES && canCompress(file)) {
        setCompressing(true);
        try {
          toSend = await gzipFile(file);
        } catch {
          toSend = file; // Compression is only a speed-up; send the file as it is.
        } finally {
          setCompressing(false);
        }
      }
      if (mb(toSend.size) > maxUploadMb) {
        onReject(
          toSend === file && isCsv
            ? `This browser can't compress files before upload, so CSVs are limited to ${maxUploadMb} MB here. Try a current Chrome, Edge, Firefox or Safari.`
            : `Even compressed, this file is ${Math.ceil(mb(toSend.size))} MB; uploads can be up to ${maxUploadMb} MB.`,
        );
        return;
      }
      onUpload(toSend);
    },
    [busy, maxCsvMb, maxExcelMb, maxUploadMb, onReject, onUpload]
  );

  return (
    <div
      className={`upload-zone ${dragover ? "dragover" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragover(true);
      }}
      onDragLeave={() => setDragover(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragover(false);
        void handleFile(e.dataTransfer.files[0]);
      }}
    >
      <div className="upload-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 16V4" />
          <path d="m7 9 5-5 5 5" />
          <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
        </svg>
      </div>
      <p className="upload-title">Drop a CSV or Excel file here</p>
      <p className="upload-sub">or choose one from your computer</p>
      <input
        ref={inputRef}
        type="file"
        aria-label="CSV or Excel file"
        accept=".csv,.gz,.xlsx,.xls"
        onChange={(e) => {
          void handleFile(e.target.files?.[0]);
          // Cleared so picking the same file again, after an error or a cancel, still starts an upload.
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className="btn"
        disabled={busy}
        onClick={() => inputRef.current?.click()}
      >
        {compressing ? "Compressing…" : loading ? "Analyzing…" : "Choose file"}
      </button>
      <p className="upload-sample">
        <button
          type="button"
          className="link-btn"
          disabled={busy}
          onClick={async () => {
            try {
              const res = await fetch(sampleDataUrl());
              if (!res.ok) throw new Error();
              void handleFile(new File([await res.text()], "sales_sample.csv", { type: "text/csv" }));
            } catch {
              onReject("The sample file couldn't be loaded. Try uploading your own file.");
            }
          }}
        >
          No file handy? Try the sample sales data
        </button>
      </p>
      <p className="upload-limits">
        CSV up to {maxCsvMb} MB, Excel up to {maxExcelMb} MB · Big CSVs are compressed before upload, and
        analyzed on a random sample of rows
      </p>
    </div>
  );
}
