import { useCallback, useEffect, useRef, useState } from "react";

interface Props {
  onUpload: (file: File) => void;
  loading: boolean;
}

export default function UploadPanel({ onUpload, loading }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragover, setDragover] = useState(false);
  const [maxUploadMb, setMaxUploadMb] = useState(500);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((data: { max_upload_mb?: number }) => {
        if (data.max_upload_mb) setMaxUploadMb(data.max_upload_mb);
      })
      .catch(() => {});
  }, []);

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file || loading) return;
      onUpload(file);
    },
    [loading, onUpload]
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
      <p style={{ marginTop: "1rem", fontSize: "0.85rem", color: "var(--muted)" }}>
        Max {maxUploadMb} MB · Analysis runs in Python (Pandas) on the server
      </p>
    </div>
  );
}
