import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.config import settings
from app.routers.analysis import read_capped

MB = 1024 * 1024


@pytest.fixture
def one_mb_cap(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)


def csv_of_size(n_bytes: int) -> bytes:
    header = b"a,b\n"
    row = b"123456,abcdef\n"
    return header + row * ((n_bytes - len(header)) // len(row) + 1)


def upload(client, content: bytes, headers=None):
    return client.post(
        "/api/upload", files={"file": ("big.csv", content, "text/csv")}, headers=headers or {}
    )


def test_default_cap_is_ten_megabytes(client):
    assert client.get("/api/health").json()["max_upload_mb"] == 10


def test_declared_size_over_cap_is_refused_before_reading(client, one_mb_cap):
    res = upload(client, csv_of_size(2 * MB))
    assert res.status_code == 413
    assert res.json()["detail"] == "File exceeds the 1 MB upload limit."


def test_file_just_over_cap_is_refused_while_reading(client, one_mb_cap):
    # Inside the multipart allowance, so the middleware lets it through and the chunked read stops it.
    res = upload(client, csv_of_size(MB + 20 * 1024))
    assert res.status_code == 413


def test_refusal_still_carries_cors_headers(client, one_mb_cap):
    res = upload(client, csv_of_size(2 * MB), headers={"Origin": "http://localhost:5173"})
    assert res.status_code == 413
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_chunked_read_stops_without_a_content_length():
    file = UploadFile(file=BytesIO(csv_of_size(3 * MB)), filename="big.csv")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_capped(file, max_bytes=MB))
    assert exc.value.status_code == 413


def test_file_under_cap_is_read_whole():
    data = csv_of_size(MB // 2)
    file = UploadFile(file=BytesIO(data), filename="ok.csv")
    assert asyncio.run(read_capped(file, max_bytes=MB)) == data


def test_empty_file_is_rejected(client):
    res = upload(client, b"")
    assert res.status_code == 400
    assert res.json()["detail"] == "The file is empty."
