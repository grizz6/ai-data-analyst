import threading

import pytest

from app import workload
from app.config import settings
from app.services.ingestion import DatasetError, load_table


def test_too_many_columns_is_refused_with_a_plain_message(monkeypatch):
    monkeypatch.setattr(settings, "max_columns", 3)
    csv = b"a,b,c,d\n1,2,3,4\n"
    with pytest.raises(DatasetError, match="4 columns; the limit is 3"):
        load_table(csv, "wide.csv")
    assert list(load_table(b"a,b,c\n1,2,3\n", "ok.csv").df.columns) == ["a", "b", "c"]


def test_too_many_columns_is_a_400_on_upload(client, monkeypatch):
    monkeypatch.setattr(settings, "max_columns", 2)
    res = client.post("/api/upload", files={"file": ("wide.csv", b"a,b,c\n1,2,3\n", "text/csv")})
    assert res.status_code == 400
    assert "the limit is 2" in res.json()["detail"]


@pytest.fixture
def slot_taken(monkeypatch):
    """Hold the only analysis slot, as a long-running upload would."""
    monkeypatch.setattr(settings, "analysis_queue_wait_seconds", 0.05)
    held = threading.Event()
    release = threading.Event()

    def hold() -> None:
        workload.run_in_slot(lambda: (held.set(), release.wait(5)))

    worker = threading.Thread(target=hold)
    worker.start()
    held.wait(5)
    yield
    release.set()
    worker.join(5)


def test_upload_while_another_is_running_gets_503_not_a_crash(client, sample_csv_bytes, slot_taken):
    res = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")})
    assert res.status_code == 503
    assert res.headers["Retry-After"] == "30"
    assert "busy" in res.json()["detail"]


@pytest.fixture
def session_id(client, sample_csv_bytes) -> str:
    return client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")}).json()["session_id"]


def test_chart_build_waits_for_the_same_slot(client, session_id, request):
    chart = {"chart_type": "histogram", "x": "units"}
    request.getfixturevalue("slot_taken")
    assert client.post(f"/api/sessions/{session_id}/charts", json=chart).status_code == 503


def test_slot_is_released_after_an_error():
    with pytest.raises(ZeroDivisionError):
        workload.run_in_slot(lambda: 1 / 0)
    assert workload.run_in_slot(lambda: "next") == "next"
