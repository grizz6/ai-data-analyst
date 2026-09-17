import pandas as pd

from app.services import pipeline
from tests.builders import workbook


def upload(client, content: bytes, filename: str):
    return client.post("/api/upload", files={"file": (filename, content, "text/csv")})


def test_health_reports_status_and_upload_cap(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["max_upload_mb"] > 0


def test_upload_runs_the_full_pipeline(client, sample_csv_bytes):
    res = upload(client, sample_csv_bytes, "sales_sample.csv")
    assert res.status_code == 200

    body = res.json()
    assert body["row_count"] == 31
    assert body["column_count"] == 5
    assert body["charts"]
    assert body["rule_insights"]
    assert {c["column_a"] for c in body["correlations"]} == {"sales"}


def test_session_can_be_fetched_after_upload(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes, "sales_sample.csv").json()["session_id"]
    res = client.get(f"/api/sessions/{session_id}")
    assert res.status_code == 200
    assert res.json()["session_id"] == session_id


def test_unsupported_file_type_is_rejected(client):
    res = upload(client, b"{}", "data.json")
    assert res.status_code == 400
    assert "Unsupported file type" in res.json()["detail"]


def test_unknown_session_is_404(client):
    assert client.get("/api/sessions/does-not-exist").status_code == 404
    assert client.get("/api/sessions/does-not-exist/report").status_code == 404


def test_blank_question_is_rejected(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes, "sales_sample.csv").json()["session_id"]
    res = client.post(f"/api/sessions/{session_id}/ask", json={"question": "   "})
    assert res.status_code == 400


def test_excel_sheet_can_be_chosen_by_query_parameter(client):
    data = workbook(Sales=pd.DataFrame({"v": range(5)}), Costs=pd.DataFrame({"c": range(8)}))
    files = {"file": ("book.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    default = client.post("/api/upload", files=files).json()
    assert (default["sheet_name"], default["row_count"]) == ("Sales", 5)
    assert default["available_sheets"] == ["Sales", "Costs"]
    assert any("also has 'Costs'" in i["message"] for i in default["rule_insights"])

    chosen = client.post("/api/upload", params={"sheet": "Costs"}, files=files).json()
    assert (chosen["sheet_name"], chosen["row_count"]) == ("Costs", 8)


def test_unexpected_errors_do_not_leak_details(client, sample_csv_bytes, monkeypatch):
    def broken(*args):
        raise RuntimeError("/Users/someone/private/path exploded")

    monkeypatch.setattr(pipeline, "compute_analysis", broken)
    res = upload(client, sample_csv_bytes, "sales_sample.csv")

    assert res.status_code == 500
    assert "private" not in res.json()["detail"]
    assert "Reference:" in res.json()["detail"]


def test_report_downloads_as_html_attachment(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes, "sales_sample.csv").json()["session_id"]
    res = client.get(f"/api/sessions/{session_id}/report")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "attachment" in res.headers["content-disposition"]
    assert "sales_sample.csv" in res.text
