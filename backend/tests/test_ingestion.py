import zipfile
from io import BytesIO

import pandas as pd
import pytest

from app.config import settings
from app.services.ingestion import DatasetError, df_preview_records, load_dataframe, load_table
from tests.builders import workbook


def test_csv_is_loaded_and_column_names_are_stripped():
    df = load_dataframe(b" region , sales\nWest,10\nEast,20\n", "data.csv")
    assert list(df.columns) == ["region", "sales"]
    assert len(df) == 2


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_csv_delimiter_is_detected(delimiter):
    text = f"region{delimiter}sales\nWest{delimiter}10\nEast{delimiter}20\n"
    df = load_dataframe(text.encode(), "data.csv")
    assert list(df.columns) == ["region", "sales"]
    assert df["sales"].tolist() == [10, 20]


def test_quoted_commas_do_not_confuse_delimiter_detection():
    df = load_dataframe(b'name,city\n"Smith, Jo","Austin, TX"\n"Lee, Al","Reno, NV"\n', "data.csv")
    assert df.loc[0, "city"] == "Austin, TX"


@pytest.mark.parametrize(
    ("encoded", "label"),
    [
        ("﻿café,price\nlatte,4\n".encode(), "utf-8 with BOM"),
        ("café,price\nlatte,4\n".encode("cp1252"), "Windows-1252 (Excel on Windows)"),
        ("café,price\ncrème brûlée,4\n".encode("latin-1"), "Latin-1"),
    ],
)
def test_csv_encodings_are_detected(encoded, label):
    df = load_dataframe(encoded, "data.csv")
    assert list(df.columns) == ["café", "price"], label


@pytest.mark.parametrize("content", [b"", b"   \n\n"])
def test_empty_csv_raises_dataset_error(content):
    with pytest.raises(DatasetError, match="empty"):
        load_dataframe(content, "data.csv")


def test_xlsx_is_loaded():
    buffer = BytesIO()
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(buffer, index=False)
    df = load_dataframe(buffer.getvalue(), "data.xlsx")
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


def test_first_sheet_with_data_is_chosen_and_all_sheets_are_listed():
    data = workbook(Notes=pd.DataFrame(), Sales=pd.DataFrame({"v": [1, 2]}), Costs=pd.DataFrame({"c": [3]}))
    table = load_table(data, "book.xlsx")
    assert table.sheet == "Sales"
    assert table.available_sheets == ["Notes", "Sales", "Costs"]
    assert table.df["v"].tolist() == [1, 2]


def test_requested_sheet_is_loaded():
    data = workbook(Sales=pd.DataFrame({"v": [1]}), Costs=pd.DataFrame({"c": [3, 4]}))
    table = load_table(data, "book.xlsx", sheet="Costs")
    assert table.sheet == "Costs"
    assert table.df["c"].tolist() == [3, 4]


def test_missing_sheet_names_the_ones_that_exist():
    data = workbook(Sales=pd.DataFrame({"v": [1]}))
    with pytest.raises(DatasetError, match="Sheet 'Q3' not found. This workbook has: Sales."):
        load_table(data, "book.xlsx", sheet="Q3")


def zip_bomb(unzipped_mb: int) -> bytes:
    """A tiny .xlsx-shaped archive whose single entry expands to unzipped_mb."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (unzipped_mb * 1024 * 1024))
    return buffer.getvalue()


def test_workbook_that_expands_past_the_limit_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "max_excel_unzipped_mb", 5)
    data = zip_bomb(6)
    assert len(data) < 100_000  # a few KB on disk, 6 MB once opened

    with pytest.raises(DatasetError, match="expands to 6 MB when opened, over the 5 MB limit"):
        load_dataframe(data, "book.xlsx")


def test_normal_workbook_passes_the_unzipped_size_check(monkeypatch):
    monkeypatch.setattr(settings, "max_excel_unzipped_mb", 1)
    data = workbook(Sales=pd.DataFrame({"v": range(100)}))
    assert load_table(data, "book.xlsx").df["v"].sum() == 4950


def test_corrupt_excel_raises_dataset_error():
    with pytest.raises(DatasetError, match="couldn't be opened"):
        load_dataframe(b"not really a workbook", "book.xlsx")


def test_unsupported_suffix_raises_dataset_error():
    with pytest.raises(DatasetError, match="Unsupported file type"):
        load_dataframe(b"{}", "data.json")


def test_preview_is_capped_and_json_safe():
    df = pd.DataFrame({"when": pd.date_range("2024-01-01", periods=30), "v": [None] + list(range(29))})
    rows = df_preview_records(df, limit=15)
    assert len(rows) == 15
    assert rows[0]["v"] is None
    assert isinstance(rows[0]["when"], str)
