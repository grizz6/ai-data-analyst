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
      <p>Drop a CSV or Excel file here, or choose a file to upload.</p>
      <input
        ref={inputRef}
        type="file"
        aria-label="CSV or Excel file"
        accept=".csv,.xlsx,.xls"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />
      <button
        type="button"
        className="btn"
        disabled={loading}
        onClick={() => inputRef.current?.click()}
      >
        {loading ? "Analyzing…" : "Choose file"}
      </button>
      <p style={{ marginTop: "0.75rem" }}>
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
      <p style={{ marginTop: "1rem", fontSize: "0.85rem", color: "var(--muted)" }}>
        CSV up to {maxUploadMb} MB, Excel up to {maxExcelMb} MB · Very large files are analyzed on a
        random sample of rows
      </p>
    </div>
  );
}
