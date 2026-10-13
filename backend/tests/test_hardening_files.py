"""Odd, broken and hostile files: each gets an analysis or a plain-English refusal, never a server error."""

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from app.config import settings


def upload(client, body: bytes, name: str = "data.csv", sheet: str | None = None):
    params = {"sheet": sheet} if sheet else None
    return client.post("/api/upload", files={"file": (name, body, "application/octet-stream")}, params=params)


def numbers(n: int = 40) -> str:
    return "".join(f"{i},{i * 2 % 17},{'abc'[i % 3]}\n" for i in range(n))


def csv(header: str, rows: str) -> bytes:
    return (header + "\n" + rows).encode()


def xlsx(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()


GOOD = csv("a,b,c", numbers())

# (case id, file name, body). Every one must be analyzed or refused with a message.
CASES = [
    ("utf8-bom", "d.csv", b"\xef\xbb\xbf" + GOOD),
    ("latin-1", "d.csv", b"name,amount\n" + "".join(f"Jos\xe9 {i},{i}\n" for i in range(20)).encode("latin-1")),
    ("utf-16", "d.csv", GOOD.decode().encode("utf-16")),
    ("semicolons", "d.csv", GOOD.decode().replace(",", ";").encode()),
    ("tabs", "d.csv", GOOD.decode().replace(",", "\t").encode()),
    ("pipes", "d.csv", GOOD.decode().replace(",", "|").encode()),
    ("windows-newlines", "d.csv", GOOD.replace(b"\n", b"\r\n")),
    ("old-mac-newlines", "d.csv", GOOD.replace(b"\n", b"\r")),
    ("ragged-rows", "d.csv", b"a,b,c\n1,2\n3,4,5,6\n7,8,9\n" * 10),
    ("quoted-newlines", "d.csv", b'a,b\n"line one\nline two",1\n"x",2\n' * 10),
    ("null-bytes", "d.csv", GOOD.replace(b",", b"\x00,", 5)),
    ("binary-garbage", "d.csv", bytes(range(256)) * 50),
    ("png-renamed", "d.csv", b"\x89PNG\r\n\x1a\n" + b"\x00" * 500),
    ("header-only", "d.csv", b"a,b,c\n"),
    ("single-row", "d.csv", b"a,b\n1,2\n"),
    ("single-column", "d.csv", ("v\n" + "".join(f"{i}\n" for i in range(30))).encode()),
    ("single-cell", "d.csv", b"x\n"),
    ("whitespace-only", "d.csv", b"   \n\n  \n"),
    ("duplicate-headers", "d.csv", csv("a,a,b", numbers())),
    ("blank-headers", "d.csv", csv(",,", numbers())),
    ("numeric-headers", "d.csv", csv("1,2,3", numbers())),
    ("long-headers", "d.csv", csv(",".join(["x" * 600, "y" * 600, "z"]), numbers())),
    ("unicode-headers", "d.csv", csv("销售,🙂 score,naïve", numbers())),
    ("html-headers", "d.csv", csv('<b>a</b>,"<script>x</script>",c', numbers())),
    ("all-empty-column", "d.csv", ("a,b\n" + "".join(f"{i},\n" for i in range(30))).encode()),
    ("all-empty-file", "d.csv", ("a,b\n" + ",\n" * 30).encode()),
    (
        "infinity-strings",
        "d.csv",
        ("a,b\n" + "".join(f"{v},{i}\n" for i, v in enumerate(["inf", "-inf", "nan", "1"] * 8))).encode(),
    ),
    ("huge-numbers", "d.csv", ("a,b\n" + "".join(f"{1e308 if i % 2 else -1e308},{i}\n" for i in range(30))).encode()),
    ("tiny-numbers", "d.csv", ("a,b\n" + "".join(f"{1e-320},{i}\n" for i in range(30))).encode()),
    (
        "mixed-types",
        "d.csv",
        ("a,b\n" + "".join(f"{v},{i}\n" for i, v in enumerate(["1", "two", "3.5", "", "x"] * 8))).encode(),
    ),
    (
        "currency-and-percent",
        "d.csv",
        ("price,share\n" + "".join(f'"${i},{i:03d}.50",{i % 100}%\n' for i in range(30))).encode(),
    ),
    ("accounting-negatives", "d.csv", ("a,b\n" + "".join(f"({i}),{i}\n" for i in range(30))).encode()),
    (
        "mixed-date-formats",
        "d.csv",
        (
            "d,v\n" + "".join(f"{f},{i}\n" for i, f in enumerate(["2024-01-05", "05/01/2024", "Jan 5 2024", "bad"] * 8))
        ).encode(),
    ),
    (
        "far-future-dates",
        "d.csv",
        ("d,v\n" + "".join(f"{y}-01-01,{i}\n" for i, y in enumerate([1, 1677, 2262, 9999] * 8))).encode(),
    ),
    (
        "booleans",
        "d.csv",
        ("flag,v\n" + "".join(f"{b},{i}\n" for i, b in enumerate(["TRUE", "false", "Yes", "no"] * 8))).encode(),
    ),
    ("constant-columns", "d.csv", ("a,b\n" + "1,x\n" * 30).encode()),
    ("all-duplicate-rows", "d.csv", ("a,b,c\n" + "1,2,x\n" * 50).encode()),
    ("emoji-values", "d.csv", ("e,v\n" + "".join(f"{'🙂🚀✨'[i % 3]},{i}\n" for i in range(30))).encode()),
    ("very-long-cells", "d.csv", ("t,v\n" + "".join(f"{'word ' * 4000},{i}\n" for i in range(20))).encode()),
    ("formula-cells", "d.csv", ("f,v\n" + "".join(f"=1+{i},{i}\n" for i in range(30))).encode()),
    ("one-numeric-two-rows", "d.csv", b"v\n1\n2\n"),
    ("negative-zero", "d.csv", ("a,b\n" + "".join(f"-0.0,{i}\n" for i in range(30))).encode()),
    ("uppercase-extension", "D.CSV", GOOD),
    ("dots-in-name", "my.data.v2.csv", GOOD),
]


@pytest.mark.parametrize(("name", "body"), [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_file_is_analyzed_or_refused_politely(client, name, body):
    res = upload(client, body, name)
    assert res.status_code in (200, 400), res.text[:300]
    if res.status_code == 400:
        detail = res.json()["detail"]
        assert isinstance(detail, str) and len(detail) > 10
        assert "Traceback" not in detail and "Error(" not in detail
    else:
        data = res.json()
        assert data["row_count"] >= 0
        # The dashboard's downloads work for whatever was accepted.
        sid = data["session_id"]
        for path in ("report", "dictionary.csv", "cleaned.csv"):
            assert client.get(f"/api/sessions/{sid}/{path}").status_code == 200, path


@pytest.mark.parametrize(
    ("name", "expected"),
    [("notes.txt", 400), ("data", 400), ("data.json", 400), ("data.csv.exe", 400), (".csv", 400)],
)
def test_only_spreadsheet_types_are_accepted(client, name, expected):
    assert upload(client, GOOD, name).status_code == expected


def test_empty_file_is_refused(client):
    res = upload(client, b"")
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_too_many_columns_is_refused(client):
    wide = (
        ",".join(f"c{i}" for i in range(settings.max_columns + 1))
        + "\n"
        + ",".join("1" for _ in range(settings.max_columns + 1))
        + "\n"
    )
    res = upload(client, wide.encode())
    assert res.status_code == 400
    assert "columns" in res.json()["detail"]


def test_large_file_is_sampled_not_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "max_analysis_rows", 500)
    rows = "".join(f"{i},{i % 7}\n" for i in range(3000))
    data = upload(client, ("a,b\n" + rows).encode()).json()
    assert data["sampled"] is True
    assert data["row_count"] == 500 and data["rows_in_file"] == 3000


# ---------- Excel ----------


def test_excel_picks_a_sheet_and_lists_them_all(client):
    body = xlsx({"First": pd.DataFrame({"a": range(20)}), "Second": pd.DataFrame({"b": range(5)})})
    first = upload(client, body, "book.xlsx").json()
    assert first["available_sheets"] == ["First", "Second"]
    second = upload(client, body, "book.xlsx", sheet="Second").json()
    assert second["sheet_name"] == "Second" and second["row_count"] == 5


def test_missing_sheet_is_refused_with_its_name(client):
    body = xlsx({"Only": pd.DataFrame({"a": range(10)})})
    res = upload(client, body, "book.xlsx", sheet="Nope")
    assert res.status_code == 400
    assert "Nope" in res.json()["detail"]


def test_empty_excel_sheet_is_refused(client):
    body = xlsx({"Empty": pd.DataFrame()})
    assert upload(client, body, "book.xlsx").status_code == 400


def test_csv_renamed_to_xlsx_is_refused(client):
    assert upload(client, GOOD, "fake.xlsx").status_code == 400


def test_corrupt_zip_is_refused(client):
    assert upload(client, b"PK\x03\x04" + b"\x00" * 200, "broken.xlsx").status_code == 400


def test_excel_zip_bomb_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "max_excel_unzipped_mb", 1)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/worksheets/sheet1.xml", "0" * (5 * 1024 * 1024))
    res = upload(client, buffer.getvalue(), "bomb.xlsx")
    assert res.status_code == 400


def test_oversized_excel_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "max_excel_mb", 0)
    body = xlsx({"S": pd.DataFrame({"a": range(10)})})
    assert upload(client, body, "book.xlsx").status_code in (400, 413)


def test_excel_with_formulas_and_dates(client):
    frame = pd.DataFrame({"when": pd.date_range("2024-01-01", periods=30), "v": np.arange(30.0), "f": ["=A1+1"] * 30})
    res = upload(client, xlsx({"S": frame}), "book.xlsx")
    assert res.status_code == 200
    assert any(v["kind"] == "date" for v in res.json()["variables"])


def test_old_xls_that_is_not_really_xls_is_refused(client):
    assert upload(client, GOOD, "old.xls").status_code == 400


# ---------- Compressed CSV uploads (the browser gzips large CSVs) ----------

import gzip  # noqa: E402


def test_gzipped_csv_is_analyzed_under_its_original_name(client):
    res = upload(client, gzip.compress(GOOD), "sales.csv.gz")
    assert res.status_code == 200
    assert res.json()["filename"] == "sales.csv"
    assert res.json()["row_count"] == 40


def test_gzipped_csv_gives_the_same_result_as_plain(client):
    plain = upload(client, GOOD, "a.csv").json()
    packed = upload(client, gzip.compress(GOOD), "a.csv.gz").json()
    for key in ("row_count", "column_count", "numeric_summaries", "correlations"):
        assert plain[key] == packed[key], key


def test_gzipped_latin1_csv_still_finds_its_encoding(client):
    body = b"name,amount\n" + "".join(f"Jos\xe9 {i},{i}\n" for i in range(20)).encode("latin-1")
    res = upload(client, gzip.compress(body), "names.csv.gz")
    assert res.status_code == 200
    assert any("José" in str(v) for row in res.json()["preview_rows"] for v in row.values())


def test_gzip_bomb_is_stopped_at_the_csv_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_csv_mb", 1)
    bomb = gzip.compress(b"a,b\n" + b"1,2\n" * (2 * 1024 * 1024))
    assert len(bomb) < 100_000
    res = upload(client, bomb, "bomb.csv.gz")
    assert res.status_code == 400
    assert "1 MB once uncompressed" in res.json()["detail"]


@pytest.mark.parametrize("cut", [10, 100, -20])
def test_damaged_gzip_is_refused(client, cut):
    body = gzip.compress(GOOD * 50)
    res = upload(client, body[:cut], "d.csv.gz")
    assert res.status_code == 400


def test_gzipped_header_only_is_handled(client):
    assert upload(client, gzip.compress(b"a,b,c\n"), "h.csv.gz").status_code in (200, 400)


def test_gzipped_empty_file_is_refused(client):
    res = upload(client, gzip.compress(b""), "e.csv.gz")
    assert res.status_code == 400


def test_gzip_with_a_plain_csv_name_is_still_read(client):
    assert upload(client, gzip.compress(GOOD), "plain-name.csv").status_code == 200


def test_other_gz_files_are_refused(client):
    assert upload(client, gzip.compress(GOOD), "data.json.gz").status_code == 400
    assert upload(client, gzip.compress(GOOD), "data.gz").status_code == 400


def test_health_reports_the_csv_limit(client):
    body = client.get("/api/health").json()
    assert body["max_csv_mb"] == settings.max_csv_mb
    assert body["max_csv_mb"] >= body["max_upload_mb"]
