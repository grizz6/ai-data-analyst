import csv
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

from app.config import settings
from app.utils.json_compat import sanitize_for_json

# Tried in order. utf-8-sig reads plain UTF-8 too and strips a BOM that would
# otherwise end up glued to the first column name. latin-1 accepts any byte,
# so it is the last resort.
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")
CSV_DELIMITERS = ",;\t|"
SNIFF_SAMPLE_BYTES = 256 * 1024
# Large CSVs are read this many rows at a time, so the whole file is never in memory.
CSV_CHUNK_ROWS = 50_000
# Fixed so the same file always gives the same sample, and so the same results.
SAMPLE_SEED = 20240501

# An upload arrives either as bytes or as the file the web framework spooled to disk.
Source = bytes | BinaryIO


class DatasetError(ValueError):
    """A problem with the uploaded file, worded for the person who uploaded it."""


@dataclass
class LoadedTable:
    df: pd.DataFrame
    sheet: str | None = None
    available_sheets: list[str] = field(default_factory=list)
    # Data rows in the file. When it's more than ADA_MAX_ANALYSIS_ROWS, df holds a
    # random sample of that many rows, in file order, keeping their row numbers.
    total_rows: int = 0

    @property
    def sampled(self) -> bool:
        return self.total_rows > len(self.df)


def load_dataframe(source: Source, filename: str, sheet: str | None = None) -> pd.DataFrame:
    return load_table(source, filename, sheet).df


def load_table(source: Source, filename: str, sheet: str | None = None) -> LoadedTable:
    suffix = Path(filename).suffix.lower()

    if suffix == ".csv":
        df, total_rows = _read_csv(_as_stream(source))
        table = LoadedTable(df=df, total_rows=total_rows)
    elif suffix in {".xlsx", ".xls"}:
        data = source if isinstance(source, bytes) else _as_stream(source).read()
        if len(data) > settings.max_excel_bytes:
            raise DatasetError(
                f"Excel files can be up to {settings.max_excel_mb} MB, since a workbook has to be opened "
                f"whole. Save the sheet as CSV (up to {settings.max_upload_mb} MB) and upload that instead."
            )
        table = _read_excel(data, sheet)
        table.total_rows = len(table.df)
        table.df = _sample_rows(table.df)
    else:
        raise DatasetError("Unsupported file type. Upload CSV or Excel (.xlsx, .xls).")

    columns = len(table.df.columns)
    if columns > settings.max_columns:
        raise DatasetError(
            f"This file has {columns:,} columns; the limit is {settings.max_columns}. "
            "Remove columns you don't need, or split the file, and upload it again."
        )
    table.df.columns = [str(c).strip() for c in table.df.columns]
    return table


def _as_stream(source: Source) -> BinaryIO:
    if isinstance(source, bytes):
        return BytesIO(source)
    source.seek(0)
    return source


def _read_csv(stream: BinaryIO) -> tuple[pd.DataFrame, int]:
    """The rows to analyze (all of them, or a sample of large files) and the file's row count."""
    head = stream.read(SNIFF_SAMPLE_BYTES)
    if not head.strip():
        raise DatasetError("The file is empty.")

    # A wrong guess at the encoding can surface anywhere in the file, so each
    # attempt reads it to the end. latin-1 accepts any byte, so the loop ends.
    for encoding in CSV_ENCODINGS:
        stream.seek(0)
        try:
            # The sample can end mid-character; that only matters for sniffing.
            delimiter = _sniff_delimiter(head.decode(encoding, errors="ignore"))
            return _sample_csv(stream, encoding, delimiter)
        except UnicodeDecodeError:
            continue
    raise DatasetError("The file's text encoding couldn't be read.")


def _sniff_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=CSV_DELIMITERS).delimiter
    except csv.Error:
        return ","


def _sample_csv(stream: BinaryIO, encoding: str, delimiter: str) -> tuple[pd.DataFrame, int]:
    """Read in chunks, keeping a uniform random sample of at most ADA_MAX_ANALYSIS_ROWS rows.

    Every row gets a random key and the rows with the smallest keys are kept,
    which samples evenly across the whole file without knowing its length.
    """
    limit = settings.max_analysis_rows
    rng = np.random.default_rng(SAMPLE_SEED)
    kept: pd.DataFrame | None = None
    keys: np.ndarray = np.empty(0)
    total = 0
    try:
        for chunk in pd.read_csv(stream, sep=delimiter, encoding=encoding, chunksize=CSV_CHUNK_ROWS):
            total += len(chunk)
            kept = chunk if kept is None else pd.concat([kept, chunk])
            keys = np.concatenate([keys, rng.random(len(chunk))])
            if len(kept) > limit:
                keep = np.sort(np.argpartition(keys, limit)[:limit])
                kept, keys = kept.iloc[keep], keys[keep]
    except pd.errors.EmptyDataError as exc:
        raise DatasetError("The file has no columns to read.") from exc
    except pd.errors.ParserError as exc:
        raise DatasetError(
            "The CSV couldn't be parsed. Check that every row has the same number of fields."
        ) from exc

    if kept is None:  # a header and no rows
        stream.seek(0)
        kept = pd.read_csv(stream, sep=delimiter, encoding=encoding, nrows=0)
    return kept.sort_index(), total


def _sample_rows(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= settings.max_analysis_rows:
        return df
    return df.sample(n=settings.max_analysis_rows, random_state=SAMPLE_SEED).sort_index()


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
