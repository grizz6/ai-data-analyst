import re

from fastapi.testclient import TestClient

from app.config import settings


def upload(client, sample_csv_bytes) -> str:
    return client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")}).json()["session_id"]


def test_every_response_carries_the_security_headers(client):
    for res in (client.get("/api/health"), client.get("/api/sessions/nope"), client.get("/")):
        assert res.headers["x-content-type-options"] == "nosniff"
        assert res.headers["referrer-policy"] == "no-referrer"
        assert res.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in res.headers["content-security-policy"]
        assert "script-src 'self'" in res.headers["content-security-policy"]


def test_analysis_data_is_never_cached(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)
    for suffix in ("", "/report", "/cleaned.csv"):
        path = f"/api/sessions/{session_id}{suffix}"
        assert client.get(path).headers["cache-control"] == "no-store", path
    assert client.get("/api/sample.csv").headers.get("cache-control") != "no-store"


def test_print_view_runs_only_its_own_nonced_script_and_local_plotly(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)
    res = client.get(f"/api/sessions/{session_id}/report?print=true")
    csp = res.headers["content-security-policy"]
    nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
    assert f'<script nonce="{nonce}">' in res.text
    assert '<script src="/api/vendor/plotly.min.js"' in res.text
    assert "cdn.plot.ly" not in res.text
    # A fresh nonce every time.
    again = client.get(f"/api/sessions/{session_id}/report?print=true").headers["content-security-policy"]
    assert again != csp


def test_downloaded_report_sends_no_referrer(client, sample_csv_bytes):
    html = client.get(f"/api/sessions/{upload(client, sample_csv_bytes)}/report").text
    assert '<meta name="referrer" content="no-referrer" />' in html


def test_plotly_is_served_locally_and_cached(client):
    res = client.get("/api/vendor/plotly.min.js")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/javascript")
    assert "max-age" in res.headers["cache-control"]
    assert b"plotly.js v2.35.2" in res.content[:400]


def test_oversized_json_body_is_refused_before_it_is_read(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)
    big = '{"goal": "' + "x" * 70_000 + '"}'
    res = client.post(f"/api/sessions/{session_id}/plan", content=big, headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_body_without_a_length_is_refused(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)

    def chunks():
        yield b'{"goal": "hi"}'

    headers = {"Content-Type": "application/json"}
    res = client.post(f"/api/sessions/{session_id}/plan", content=chunks(), headers=headers)
    assert res.status_code == 411


def test_overlong_goal_is_rejected(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)
    assert client.post(f"/api/sessions/{session_id}/plan", json={"goal": "g" * 1_001}).status_code == 422


def test_api_docs_can_be_turned_off(monkeypatch):
    import importlib

    import app.main

    monkeypatch.setattr(settings, "api_docs", False)
    try:
        quiet = TestClient(importlib.reload(app.main).app)
        assert quiet.get("/docs").status_code == 404
        assert quiet.get("/openapi.json").status_code == 404
    finally:
        monkeypatch.setattr(settings, "api_docs", True)
        importlib.reload(app.main)


def test_deleting_an_analysis_removes_everything_stored_with_it(client, sample_csv_bytes):
    session_id = upload(client, sample_csv_bytes)
    client.post(f"/api/sessions/{session_id}/plan", json={"goal": "What stands out?"})

    assert client.delete(f"/api/sessions/{session_id}").status_code == 204
    for suffix in ("", "/report", "/cleaned.csv", "/dictionary.csv"):
        assert client.get(f"/api/sessions/{session_id}{suffix}").status_code == 404
    assert client.post(f"/api/sessions/{session_id}/plan", json={"goal": "x"}).status_code == 404
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404
