import csv
import zipfile
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd

from app.config import settings
from app.utils.json_compat import sanitize_for_json

# Tried in order. utf-8-sig reads plain UTF-8 too and strips a BOM that would
# otherwise end up glued to the first column name. latin-1 accepts any byte,
# so it is the last resort.
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
CSV_DELIMITERS = ",;\t|"
SNIFF_SAMPLE_CHARS = 64_000


class DatasetError(ValueError):
    """A problem with the uploaded file, worded for the person who uploaded it."""


@dataclass
class LoadedTable:
    df: pd.DataFrame
    sheet: str | None = None
    available_sheets: list[str] = field(default_factory=list)


def load_dataframe(file_bytes: bytes, filename: str, sheet: str | None = None) -> pd.DataFrame:
    return load_table(file_bytes, filename, sheet).df


def load_table(file_bytes: bytes, filename: str, sheet: str | None = None) -> LoadedTable:
    suffix = Path(filename).suffix.lower()

    if suffix == ".csv":
        table = LoadedTable(df=_read_csv(file_bytes))
    elif suffix in {".xlsx", ".xls"}:
        table = _read_excel(file_bytes, sheet)
    else:
        raise DatasetError("Unsupported file type. Upload CSV or Excel (.xlsx, .xls).")

    table.df.columns = [str(c).strip() for c in table.df.columns]
    return table


def _read_csv(file_bytes: bytes) -> pd.DataFrame:
    text = _decode(file_bytes)
    if not text.strip():
        raise DatasetError("The file is empty.")

    try:
        delimiter = csv.Sniffer().sniff(text[:SNIFF_SAMPLE_CHARS], delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        delimiter = ","

    try:
        return pd.read_csv(StringIO(text), sep=delimiter)
    except pd.errors.EmptyDataError as exc:
        raise DatasetError("The file has no columns to read.") from exc
    except pd.errors.ParserError as exc:
        raise DatasetError(
            "The CSV couldn't be parsed. Check that every row has the same number of fields."
        ) from exc


def _decode(file_bytes: bytes) -> str:
    for encoding in CSV_ENCODINGS:
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DatasetError("The file's text encoding couldn't be read.")  # unreachable: latin-1 decodes anything


def _check_unzipped_size(file_bytes: bytes) -> None:
    """Refuse an .xlsx that would expand past the limit once unzipped.

    An .xlsx is a zip archive, and zip compresses repetitive XML extremely
    well, so a file under the upload cap can expand to gigabytes when opened.
    The sizes are read from the archive's directory, without decompressing.
    A file that under-declares its size gains nothing: Python's zipfile, which
    openpyxl reads through, stops at the declared size.
    """
    if not zipfile.is_zipfile(BytesIO(file_bytes)):
        return  # legacy .xls, or not an archive at all; the parser decides
    with zipfile.ZipFile(BytesIO(file_bytes)) as archive:
        unzipped = sum(info.file_size for info in archive.infolist())
    limit = settings.max_excel_unzipped_mb * 1024 * 1024
    if unzipped > limit:
        raise DatasetError(
            f"This workbook expands to {unzipped / 1024 / 1024:,.0f} MB when opened, over the "
            f"{settings.max_excel_unzipped_mb} MB limit. Save the sheet you need as CSV and upload that."
        )


def _read_excel(file_bytes: bytes, sheet: str | None) -> LoadedTable:
    _check_unzipped_size(file_bytes)
    try:
        workbook = pd.ExcelFile(BytesIO(file_bytes))
    except Exception as exc:
        raise DatasetError("The Excel file couldn't be opened. It may be corrupted or password-protected.") from exc

    names = [str(n) for n in workbook.sheet_names]
    if sheet is not None:
        if sheet not in names:
            raise DatasetError(f"Sheet '{sheet}' not found. This workbook has: {', '.join(names)}.")
        return LoadedTable(df=workbook.parse(sheet), sheet=sheet, available_sheets=names)

    # Workbooks often open with a cover or notes sheet, so take the first one that has data.
    for name in names:
        df = workbook.parse(name)
        if not df.empty:
            return LoadedTable(df=df, sheet=name, available_sheets=names)

    raise DatasetError("Every sheet in this workbook is empty.")


def df_preview_records(df: pd.DataFrame, limit: int = 15) -> list[dict]:
    preview = df.head(limit).copy()
    for col in preview.columns:
        if pd.api.types.is_datetime64_any_dtype(preview[col]):
            preview[col] = preview[col].astype(str)
    preview = preview.where(preview.notna(), None)
    records = preview.to_dict(orient="records")
    return sanitize_for_json(records)
