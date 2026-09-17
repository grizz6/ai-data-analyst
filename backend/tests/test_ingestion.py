from io import BytesIO

import pandas as pd
import pytest

from app.services.ingestion import df_preview_records, load_dataframe


def test_csv_is_loaded_and_column_names_are_stripped():
    df = load_dataframe(b" region , sales\nWest,10\nEast,20\n", "data.csv")
    assert list(df.columns) == ["region", "sales"]
    assert len(df) == 2


def test_xlsx_is_loaded():
    buffer = BytesIO()
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(buffer, index=False)
    df = load_dataframe(buffer.getvalue(), "data.xlsx")
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


def test_unsupported_suffix_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_dataframe(b"{}", "data.json")


def test_preview_is_capped_and_json_safe():
    df = pd.DataFrame({"when": pd.date_range("2024-01-01", periods=30), "v": [None] + list(range(29))})
    rows = df_preview_records(df, limit=15)
    assert len(rows) == 15
    assert rows[0]["v"] is None
    assert isinstance(rows[0]["when"], str)
