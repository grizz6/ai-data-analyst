from io import BytesIO
from pathlib import Path

import pandas as pd

from app.utils.json_compat import sanitize_for_json


def load_dataframe(file_bytes: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    buffer = BytesIO(file_bytes)

    if suffix == ".csv":
        df = pd.read_csv(buffer)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(buffer, engine="openpyxl" if suffix == ".xlsx" else None)
    else:
        raise ValueError("Unsupported file type. Upload CSV or Excel (.xlsx, .xls).")

    df.columns = [str(c).strip() for c in df.columns]
    return df


def df_preview_records(df: pd.DataFrame, limit: int = 15) -> list[dict]:
    preview = df.head(limit).copy()
    for col in preview.columns:
        if pd.api.types.is_datetime64_any_dtype(preview[col]):
            preview[col] = preview[col].astype(str)
    preview = preview.where(preview.notna(), None)
    records = preview.to_dict(orient="records")
    return sanitize_for_json(records)
