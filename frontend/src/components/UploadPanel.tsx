import { useCallback, useEffect, useRef, useState } from "react";
import { sampleDataUrl } from "../api";

interface Props {
  onUpload: (file: File) => void;
  onReject: (message: string) => void;
  loading: boolean;
}

export default function UploadPanel({ onUpload, onReject, loading }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragover, setDragover] = useState(false);
  const [maxUploadMb, setMaxUploadMb] = useState(75);
  const [maxExcelMb, setMaxExcelMb] = useState(15);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((data: { max_upload_mb?: number; max_excel_mb?: number }) => {
        if (data.max_upload_mb) setMaxUploadMb(data.max_upload_mb);
        if (data.max_excel_mb) setMaxExcelMb(data.max_excel_mb);
      })
      .catch(() => {});
  }, []);

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file || loading) return;
      // Same limits the server enforces; checking here saves sending a file that will be refused.
      const isExcel = /\.xlsx?$/i.test(file.name);
      if (isExcel && file.size > maxExcelMb * 1024 * 1024) {
        onReject(`Excel files can be up to ${maxExcelMb} MB. Save the sheet as CSV (up to ${maxUploadMb} MB) instead.`);
        return;
      }
      if (file.size > maxUploadMb * 1024 * 1024) {
        onReject(`File exceeds the ${maxUploadMb} MB upload limit.`);
        return;
      }
      onUpload(file);
    },
    [loading, maxExcelMb, maxUploadMb, onReject, onUpload]
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
        handleFile(e.dataTransfer.files[0]);
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
        accept=".csv,.xlsx,.xls"
        onChange={(e) => {
          handleFile(e.target.files?.[0]);
          // Cleared so picking the same file again, after an error or a cancel, still starts an upload.
          e.target.value = "";
        }}
      />
      <button
        type="button"
        className="btn"
        disabled={loading}
        onClick={() => inputRef.current?.click()}
      >
        {loading ? "Analyzing…" : "Choose file"}
      </button>
      <p className="upload-sample">
        <button
          type="button"
          className="link-btn"
          disabled={loading}
          onClick={async () => {
            try {
              const res = await fetch(sampleDataUrl());
              if (!res.ok) throw new Error();
              handleFile(new File([await res.text()], "sales_sample.csv", { type: "text/csv" }));
            } catch {
              onReject("The sample file couldn't be loaded. Try uploading your own file.");
            }
          }}
        >
          No file handy? Try the sample sales data
        </button>
      </p>
      <p className="upload-limits">
        CSV up to {maxUploadMb} MB, Excel up to {maxExcelMb} MB · Very large files are analyzed on a
        random sample of rows
      </p>
    </div>
  );
}
