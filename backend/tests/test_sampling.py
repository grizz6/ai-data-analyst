import io

import numpy as np
import pandas as pd
import pytest

from app.config import settings
from app.services import ingestion
from app.services.ingestion import DatasetError, load_table
from app.services.pipeline import compute_analysis
from tests.builders import workbook


@pytest.fixture
def small_cap(monkeypatch):
    monkeypatch.setattr(settings, "max_analysis_rows", 1_000)
    monkeypatch.setattr(ingestion, "CSV_CHUNK_ROWS", 700)  # several chunks, not a multiple of the cap


def numbered_csv(rows: int) -> bytes:
    df = pd.DataFrame({"n": np.arange(rows), "half": np.where(np.arange(rows) < rows // 2, "first", "second")})
    return df.to_csv(index=False).encode()


def test_small_files_are_read_whole(small_cap):
    table = load_table(numbered_csv(900), "small.csv")
    assert (len(table.df), table.total_rows, table.sampled) == (900, 900, False)
    assert table.df["n"].tolist() == list(range(900))


def test_large_csv_is_sampled_evenly_in_file_order_with_original_row_numbers(small_cap):
    table = load_table(numbered_csv(10_000), "big.csv")

    assert (len(table.df), table.total_rows, table.sampled) == (1_000, 10_000, True)
    assert table.df["n"].is_monotonic_increasing
    assert (table.df.index == table.df["n"]).all()  # row references still point at the right line
    # Drawn from the whole file, not just its start: both halves are well represented.
    assert 400 < (table.df["half"] == "second").sum() < 600


def test_the_same_file_always_gives_the_same_sample(small_cap):
    data = numbered_csv(5_000)
    assert load_table(data, "a.csv").df["n"].tolist() == load_table(data, "a.csv").df["n"].tolist()


def test_reads_from_a_spooled_file_as_well_as_bytes(small_cap):
    data = numbered_csv(3_000)
    from_file = load_table(io.BytesIO(data), "f.csv")
    assert from_file.df["n"].tolist() == load_table(data, "f.csv").df["n"].tolist()


def test_encoding_problem_late_in_a_large_file_falls_back(monkeypatch):
    monkeypatch.setattr(ingestion, "CSV_CHUNK_ROWS", 700)  # the bad byte is several chunks in
    lines = ["city,v"] + [f"Paris,{i}" for i in range(4_000)] + ["Zürich,1"]
    data = "\n".join(lines).encode("cp1252")  # not valid UTF-8, but only at the very end
    table = load_table(data, "late.csv")
    assert table.total_rows == 4_001
    assert table.df["city"].iloc[-1] == "Zürich"


def test_excel_over_its_cap_is_refused_with_advice(monkeypatch):
    monkeypatch.setattr(settings, "max_excel_mb", 0)
    data = workbook(Sheet1=pd.DataFrame({"v": range(10)}))
    with pytest.raises(DatasetError, match="Save the sheet as CSV"):
        load_table(data, "book.xlsx")


def test_large_excel_is_sampled_too(small_cap):
    data = workbook(Sheet1=pd.DataFrame({"v": range(3_000)}))
    table = load_table(data, "book.xlsx")
    assert (len(table.df), table.total_rows, table.sampled) == (1_000, 3_000, True)


def test_analysis_says_it_used_a_sample(small_cap):
    result = compute_analysis(numbered_csv(5_000), "big.csv")
    assert (result.row_count, result.rows_in_file, result.sampled) == (1_000, 5_000, True)
    sample_note = next(i for i in result.rule_insights if i.title == "Sample")
    assert "5,000 rows" in sample_note.message and "1,000 rows" in sample_note.message


def test_upload_endpoint_analyzes_a_spooled_large_file(client, small_cap):
    res = client.post("/api/upload", files={"file": ("big.csv", numbered_csv(20_000), "text/csv")})
    assert res.status_code == 200
    body = res.json()
    assert (body["row_count"], body["rows_in_file"], body["sampled"]) == (1_000, 20_000, True)
