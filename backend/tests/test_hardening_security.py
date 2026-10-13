"""Server-side hardening: secrets, data leaks, headers, sessions and request handling.

Every test here is a way the live site could leak a key or a visitor's data,
or be pushed into an error, checked end to end through the HTTP API.
"""

import json
import logging
import sqlite3
from pathlib import Path

import httpx
import pytest

from app import session_store
from app.config import Settings, settings
from app.main import app
from app.services import explanation
from app.services.llm_client import LLMClient

SECRET_KEY = "gsk_live_SECRET_do_not_leak_1234567890abcdef"
REPO = Path(__file__).resolve().parents[2]


def upload(client, body: bytes, name: str = "data.csv", **kwargs):
    return client.post("/api/upload", files={"file": (name, body, "text/csv")}, **kwargs)


def session_id(client, body: bytes, name: str = "data.csv") -> str:
    res = upload(client, body, name)
    assert res.status_code == 200, res.text
    return res.json()["session_id"]


# A file with one obviously private value per row, so any leak of raw rows is visible.
PRIVATE_CSV = (
    "customer_email,ssn,amount,region\n"
    + "".join(f"person{i}@private.example,123-45-{i:04d},{i * 3 % 50 + 10},{'NSEW'[i % 4]}\n" for i in range(60))
).encode()


class RecordingModel:
    """A fake provider that records what the app sends and replies with a fixed body."""

    def __init__(self, reply: httpx.Response | Exception | None = None):
        self.reply = reply
        self.requests: list[httpx.Request] = []

    def client(self) -> LLMClient:
        async def no_sleep(_: float) -> None:
            return None

        return LLMClient(
            api_key=settings.llm_api_key,
            base_url="https://llm.test/v1",
            model="test-model",
            max_retries=0,
            transport=httpx.MockTransport(self._handle),
            sleep=no_sleep,
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.reply, Exception):
            raise self.reply
        if self.reply is not None:
            return self.reply
        return httpx.Response(401, json={"error": f"invalid key {SECRET_KEY}"})

    @property
    def sent_text(self) -> str:
        return "\n".join(r.content.decode() for r in self.requests)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", SECRET_KEY)


@pytest.fixture
def model(monkeypatch, with_key):
    fake = RecordingModel()
    monkeypatch.setattr(explanation, "make_client", fake.client)
    import app.services.advice as advice

    if hasattr(advice, "make_client"):
        monkeypatch.setattr(advice, "make_client", fake.client)
    return fake


# ---------- API keys never leave the server ----------


def test_health_reports_a_key_without_revealing_it(client, with_key):
    body = client.get("/api/health").text
    assert SECRET_KEY not in body
    assert json.loads(body)["llm_configured"] is True


def test_settings_repr_hides_the_key():
    shown = Settings(llm_api_key=SECRET_KEY)
    assert SECRET_KEY not in repr(shown)
    assert SECRET_KEY not in str(shown.model_dump())


def test_key_is_sent_only_as_a_bearer_header(client, model, sample_csv_bytes):
    upload(client, sample_csv_bytes)
    assert model.requests, "the model should have been called"
    for request in model.requests:
        assert request.headers["authorization"] == f"Bearer {SECRET_KEY}"
        assert SECRET_KEY not in request.content.decode()
        assert SECRET_KEY not in str(request.url)


def test_provider_error_echoing_the_key_never_reaches_the_visitor(client, model, sample_csv_bytes):
    res = upload(client, sample_csv_bytes)
    assert res.status_code == 200
    assert SECRET_KEY not in res.text
    assert res.json()["explanation"]["source"] == "rule_based"


def test_connection_error_text_never_reaches_the_visitor(client, model, sample_csv_bytes):
    model.reply = httpx.ConnectError(f"could not reach host with key {SECRET_KEY}")
    res = upload(client, sample_csv_bytes)
    assert res.status_code == 200
    assert SECRET_KEY not in res.text


def test_key_never_written_to_the_logs(client, model, sample_csv_bytes, caplog):
    with caplog.at_level(logging.DEBUG):
        upload(client, sample_csv_bytes)
    assert SECRET_KEY not in caplog.text


def test_key_not_in_reports_or_downloads(client, model, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    for path in ("report", "report?print=true", "dictionary.csv", "cleaned.csv", ""):
        res = client.get(f"/api/sessions/{sid}/{path}".rstrip("/"))
        assert res.status_code == 200, path
        assert SECRET_KEY not in res.text, path


def test_plan_errors_do_not_leak_the_key(client, model, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    res = client.post(f"/api/sessions/{sid}/plan", json={"goal": "Grow sales"})
    assert res.status_code == 200
    assert SECRET_KEY not in res.text


# ---------- What the language model is given ----------


def test_model_never_receives_raw_private_rows(client, model):
    upload(client, PRIVATE_CSV)
    sent = model.sent_text
    assert sent, "the model should have been called"
    assert "@private.example" not in sent
    assert "123-45-" not in sent


def test_model_receives_no_preview_rows(client, model, sample_csv_bytes):
    res = upload(client, sample_csv_bytes)
    first_row = res.json()["preview_rows"][0]
    sent = json.loads(json.loads(model.requests[0].content)["messages"][1]["content"])
    assert "preview_rows" not in json.dumps(sent)
    assert first_row  # the visitor still gets their own preview


def test_without_a_key_nothing_is_sent_anywhere(client, monkeypatch, sample_csv_bytes):
    fake = RecordingModel()
    monkeypatch.setattr(explanation, "make_client", fake.client)
    upload(client, PRIVATE_CSV)
    assert fake.requests == []


# ---------- Errors never reveal internals ----------


def test_unexpected_error_returns_only_a_reference(client, monkeypatch, sample_csv_bytes):
    from app.routers import analysis as router

    async def broken(*_args, **_kwargs):
        raise RuntimeError(f"/secret/path/{SECRET_KEY} row value person1@private.example")

    monkeypatch.setattr(router, "run_full_analysis", broken)
    res = upload(client, sample_csv_bytes)
    assert res.status_code == 500
    assert "Reference:" in res.json()["detail"]
    assert SECRET_KEY not in res.text and "private.example" not in res.text and "/secret" not in res.text


def test_unknown_api_path_is_a_json_404(client):
    res = client.get("/api/does-not-exist")
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/json")


def test_wrong_method_is_refused(client):
    assert client.put("/api/upload", content=b"x", headers={"content-length": "1"}).status_code == 405


# ---------- Response headers ----------


@pytest.mark.parametrize("path", ["/api/health", "/api/does-not-exist", "/api/sessions/nope"])
def test_security_headers_on_every_kind_of_response(client, path):
    headers = client.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_security_headers_on_refused_uploads(client):
    res = client.post("/api/upload", content=b"x", headers={"content-length": str(10**12)})
    assert res.status_code == 413
    assert res.headers["x-frame-options"] == "DENY"


def test_session_data_is_never_cached(client, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    for path in ("", "/report", "/dictionary.csv", "/cleaned.csv"):
        assert client.get(f"/api/sessions/{sid}{path}").headers["cache-control"] == "no-store"


def test_csp_allows_no_third_party_scripts():
    from app.security import APP_CSP

    script = next(p for p in APP_CSP.split("; ") if p.startswith("script-src"))
    assert script == "script-src 'self'"
    assert "unsafe-eval" not in APP_CSP


# ---------- CORS ----------


def test_foreign_origin_is_not_allowed(client):
    res = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_foreign_preflight_is_refused(client):
    res = client.options(
        "/api/upload",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert res.headers.get("access-control-allow-origin") != "https://evil.example"


def test_configured_origin_is_allowed(client):
    res = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


# ---------- Sessions ----------


def test_session_ids_are_random_uuids(client, sample_csv_bytes):
    a, b = session_id(client, sample_csv_bytes), session_id(client, sample_csv_bytes)
    assert a != b
    assert len(a) == 36 and a.count("-") == 4


@pytest.mark.parametrize(
    "sid",
    ["' OR '1'='1", "1; DROP TABLE sessions", "%00", "..", "a" * 5000, "😀", "../../etc/passwd"],
)
def test_odd_session_ids_are_a_clean_404(client, sid):
    res = client.get(f"/api/sessions/{sid}")
    assert res.status_code == 404


def test_sql_injection_in_session_id_leaves_others_intact(client, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    client.delete("/api/sessions/' OR '1'='1")
    client.delete("/api/sessions/%25")
    assert client.get(f"/api/sessions/{sid}").status_code == 200


def test_deleted_analysis_is_gone_from_every_endpoint(client, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    for path in ("", "/report", "/dictionary.csv", "/cleaned.csv"):
        assert client.get(f"/api/sessions/{sid}{path}").status_code == 404
    assert client.post(f"/api/sessions/{sid}/plan", json={"goal": "x"}).status_code == 404
    assert client.delete(f"/api/sessions/{sid}").status_code == 404


def test_deleted_analysis_is_gone_from_the_database_file(tmp_path, result_for_store):
    store = session_store.SessionStore(path=tmp_path / "s.db", ttl_seconds=3600, max_sessions=5)
    store.save(result_for_store)
    store.delete(result_for_store.session_id)
    store.close()
    rows = sqlite3.connect(tmp_path / "s.db").execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert rows == 0
    # Not just unlinked: the bytes themselves are gone from the file.
    assert result_for_store.session_id.encode() not in (tmp_path / "s.db").read_bytes()


def test_expired_analysis_is_removed(tmp_path, result_for_store):
    now = [1000.0]
    store = session_store.SessionStore(path=":memory:", ttl_seconds=60, max_sessions=5, clock=lambda: now[0])
    store.save(result_for_store)
    now[0] += 61
    assert store.get(result_for_store.session_id) is None
    assert len(store) == 0


def test_responses_never_carry_the_stored_csv(client, sample_csv_bytes):
    res = upload(client, sample_csv_bytes)
    assert "cleaned_csv" not in res.json()
    assert "charts" not in res.json()
    again = client.get(f"/api/sessions/{res.json()['session_id']}").json()
    assert "cleaned_csv" not in again and "charts" not in again


# ---------- Request size and shape ----------


def test_upload_without_a_length_is_refused(client, sample_csv_bytes):
    def chunks():
        yield b'--b\r\nContent-Disposition: form-data; name="file"; filename="a.csv"\r\n\r\n'
        yield sample_csv_bytes
        yield b"\r\n--b--\r\n"

    res = client.post(
        "/api/upload",
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=b", "transfer-encoding": "chunked"},
    )
    assert res.status_code == 411


def test_declared_oversize_upload_is_refused_before_reading(client):
    res = client.post(
        "/api/upload",
        content=b"tiny",
        headers={"content-type": "multipart/form-data; boundary=b", "content-length": str(10**10)},
    )
    assert res.status_code == 413
    assert "MB" in res.json()["detail"]


def test_plan_with_wrong_json_shape_is_a_422(client, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    assert client.post(f"/api/sessions/{sid}/plan", json={"nope": 1}).status_code == 422
    assert client.post(f"/api/sessions/{sid}/plan", json={"goal": 5}).status_code == 422


def test_plan_with_invalid_json_is_a_422(client, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    res = client.post(f"/api/sessions/{sid}/plan", content=b"{not json", headers={"content-type": "application/json"})
    assert res.status_code == 422


def test_blank_goal_is_refused(client, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    assert client.post(f"/api/sessions/{sid}/plan", json={"goal": "   "}).status_code == 400


def test_upload_field_must_be_named_file(client, sample_csv_bytes):
    res = client.post("/api/upload", files={"data": ("a.csv", sample_csv_bytes, "text/csv")})
    assert res.status_code == 422


# ---------- Rate limits ----------


def test_spoofed_forwarded_for_does_not_reset_the_limit(client, monkeypatch, sample_csv_bytes):
    monkeypatch.setattr(settings, "uploads_per_hour", 2)
    for i in range(2):
        assert upload(client, sample_csv_bytes, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code == 200
    blocked = upload(client, sample_csv_bytes, headers={"X-Forwarded-For": "10.9.9.9"})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0


def test_plans_are_rate_limited(client, monkeypatch, sample_csv_bytes):
    monkeypatch.setattr(settings, "plans_per_hour", 1)
    sid = session_id(client, sample_csv_bytes)
    assert client.post(f"/api/sessions/{sid}/plan", json={"goal": "a"}).status_code == 200
    assert client.post(f"/api/sessions/{sid}/plan", json={"goal": "b"}).status_code == 429


# ---------- Downloads and the report ----------


@pytest.mark.parametrize(
    "name",
    ['evil"\r\nSet-Cookie: x=1.csv', "../../etc/passwd.csv", "名前 データ.csv", "<script>.csv", "a;b=c.csv"],
)
def test_download_filenames_cannot_inject_headers(client, sample_csv_bytes, name):
    sid = session_id(client, sample_csv_bytes, name)
    for path in ("/cleaned.csv", "/dictionary.csv", "/report"):
        res = client.get(f"/api/sessions/{sid}{path}")
        assert res.status_code == 200
        disposition = res.headers["content-disposition"]
        assert "\r" not in disposition and "\n" not in disposition
        assert "set-cookie" not in {k.lower() for k in res.headers}
        quoted = disposition.split('filename="', 1)[1].rstrip('"')
        assert '"' not in quoted and "/" not in quoted


XSS = '<img src=x onerror="alert(1)">'


def test_report_escapes_markup_in_file_and_column_names(client):
    body = f"{XSS},amount\nA,1\nB,2\nC,3\n".encode()
    sid = session_id(client, body, f"{XSS}.csv")
    for path in ("/report", "/report?print=true"):
        html = client.get(f"/api/sessions/{sid}{path}").text
        assert XSS not in html
        assert "&lt;img" in html or "\\u003cimg" in html


def test_report_escapes_markup_in_cell_values(client):
    body = ("label,amount\n" + "".join(f"{XSS},{i}\n" for i in range(20))).encode()
    sid = session_id(client, body)
    html = client.get(f"/api/sessions/{sid}/report").text
    assert XSS not in html


def test_report_escapes_markup_written_by_the_model(client, model, sample_csv_bytes):
    reply = {
        "dataset_overview": f"Hello {XSS}",
        "analysis_summary": "</script><script>alert(1)</script>",
        "recommendations": [XSS],
        "chart_explanations": [],
    }
    model.reply = httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})
    sid = session_id(client, sample_csv_bytes)
    for path in ("/report", "/report?print=true"):
        html = client.get(f"/api/sessions/{sid}{path}").text
        assert XSS not in html
        assert "<script>alert(1)</script>" not in html


def test_print_view_has_a_fresh_nonce_each_time(client, sample_csv_bytes):
    sid = session_id(client, sample_csv_bytes)
    a = client.get(f"/api/sessions/{sid}/report?print=true").headers["content-security-policy"]
    b = client.get(f"/api/sessions/{sid}/report?print=true").headers["content-security-policy"]
    assert "nonce-" in a and a != b


@pytest.mark.parametrize("value", ['=HYPERLINK("http://evil")', "+cmd|' /C calc'!A0", "@SUM(1)", "-2+3=x"])
def test_dictionary_neutralises_spreadsheet_formulas(client, value):
    body = ("label,amount\n" + "".join(f"{value},{i}\n" for i in range(10))).encode()
    sid = session_id(client, body)
    text = client.get(f"/api/sessions/{sid}/dictionary.csv").text
    for line in text.splitlines():
        for cell in line.split(","):
            assert not cell.strip('"').startswith(("=", "+", "@")), line


# ---------- Static files ----------


@pytest.mark.parametrize("path", ["/..%2f..%2fetc%2fpasswd", "/%2e%2e/%2e%2e/etc/passwd", "/....//....//etc/passwd"])
def test_static_paths_cannot_escape_the_build(tmp_path, path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.frontend import mount_frontend

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    (tmp_path / "secret.txt").write_text("TOP SECRET")
    test_app = FastAPI()
    mount_frontend(test_app, dist)
    res = TestClient(test_app).get(path)
    assert "TOP SECRET" not in res.text
    assert "root:" not in res.text


def test_app_object_is_importable_once():
    assert app.title


# ---------- Secrets in the repository and build ----------

SECRET_PATTERNS = ("gsk_", "sk-proj-", "AKIA", "ghp_", "-----BEGIN", "xoxb-")


def _tracked_files() -> list[Path]:
    import subprocess

    try:
        out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [REPO / line for line in out.splitlines() if line]


def test_no_secrets_in_tracked_files():
    offenders = []
    for path in _tracked_files():
        if path.suffix in {".png", ".jpg", ".ico", ".woff2", ".xlsx"} or not path.is_file():
            continue
        # The leak tests themselves name the patterns they look for.
        if path.name.startswith("test_hardening") or path.name == "hardening.test.tsx":
            continue
        text = path.read_text(errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern in text and path.name != Path(__file__).name:
                offenders.append(f"{path.relative_to(REPO)}: {pattern}")
    assert offenders == []


def test_env_files_are_never_committed_or_shipped():
    names = {p.name for p in _tracked_files()}
    assert ".env" not in names
    assert ".env" in (REPO / ".gitignore").read_text()
    assert "**/.env" in (REPO / ".dockerignore").read_text()


def test_container_runs_as_an_unprivileged_user():
    dockerfile = (REPO / "Dockerfile").read_text()
    assert "\nUSER app" in dockerfile


def test_render_blueprint_keeps_the_key_out_of_the_repo():
    blueprint = (REPO / "render.yaml").read_text()
    block = blueprint.split("ADA_LLM_API_KEY", 1)[1].split("- key:", 1)[0]
    assert "sync: false" in block and "value:" not in block


def test_built_frontend_contains_no_secrets_or_third_party_calls():
    dist = REPO / "frontend" / "dist" / "assets"
    if not dist.is_dir():
        pytest.skip("frontend not built")
    for js in dist.glob("*.js"):
        text = js.read_text(errors="ignore")
        for pattern in ("gsk_", "ADA_LLM", "api.groq.com", "Bearer "):
            assert pattern not in text, f"{js.name}: {pattern}"
