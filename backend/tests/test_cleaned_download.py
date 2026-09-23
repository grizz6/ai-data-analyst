from io import BytesIO

import pandas as pd
import pytest

from app.routers.analysis import cleaned_filename


def upload(client, content: bytes, filename: str) -> str:
    res = client.post("/api/upload", files={"file": (filename, content, "text/csv")})
    assert res.status_code == 200
    return res.json()["session_id"]


def download(client, session_id: str):
    return client.get(f"/api/sessions/{session_id}/cleaned.csv")


def test_cleaned_csv_downloads_every_row(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes, "sales_sample.csv")
    res = download(client, session_id)

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="sales_sample-cleaned.csv"' in res.headers["content-disposition"]
    df = pd.read_csv(BytesIO(res.content), encoding="utf-8-sig")
    assert len(df) == 31  # the whole file, not the 15-row preview
    assert list(df.columns) == ["date", "region", "product", "sales", "units"]


def test_cleaned_csv_contains_the_cleaned_values(client):
    messy = pd.DataFrame(
        {
            "row": range(20),
            "region": ["West", "west ", "East", "EAST"] * 5,
            "price": ["$1,200", "$950", "$1,050", "$990"] * 5,
        }
    )
    session_id = upload(client, messy.to_csv(index=False).encode(), "messy.csv")
    df = pd.read_csv(BytesIO(download(client, session_id).content), encoding="utf-8-sig")

    assert set(df["region"]) == {"West", "East"}
    assert df["price"].tolist()[:4] == [1200.0, 950.0, 1050.0, 990.0]


def test_cleaned_csv_is_not_in_the_json_response(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes, "sales_sample.csv")
    body = client.get(f"/api/sessions/{session_id}").json()
    assert "cleaned_csv" not in body and "_cleaned_csv" not in body


def test_unknown_session_has_no_download(client):
    assert download(client, "nope").status_code == 404


@pytest.mark.parametrize(
    ("original", "expected"),
    [
        ("sales.csv", "sales-cleaned.csv"),
        ("Q3 sales (final).xlsx", "Q3-sales-final-cleaned.csv"),
        ('evil"; name.csv', "evil-name-cleaned.csv"),
        ("...csv", "data-cleaned.csv"),
    ],
)
def test_download_filename_is_safe(original, expected):
    assert cleaned_filename(original) == expected
