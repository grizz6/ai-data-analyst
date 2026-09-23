import sqlite3

import pytest

from app.models.schemas import AnalysisResult, Explanation
from app.session_store import SessionStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_790_000_000.0  # wall-clock seconds, as time.time() returns

    def __call__(self) -> float:
        return self.now


def result(session_id: str, cleaned_csv: bytes | None = None) -> AnalysisResult:
    r = AnalysisResult(
        session_id=session_id,
        filename="f.csv",
        row_count=0,
        column_count=0,
        columns=[],
        quality_issues=[],
        cleaning_actions=[],
        numeric_summaries=[],
        categorical_summaries=[],
        correlations=[],
        trends=[],
        rule_insights=[],
        charts=[],
        explanation=Explanation(dataset_overview="", chart_explanations=[], analysis_summary="", recommendations=[]),
        preview_rows=[],
        cleaned_preview_rows=[],
    )
    r._cleaned_csv = cleaned_csv
    return r


@pytest.fixture
def clock():
    return FakeClock()


def make_store(clock, path=":memory:", ttl=60, cap=10) -> SessionStore:
    return SessionStore(path=path, ttl_seconds=ttl, max_sessions=cap, clock=clock)


def test_session_expires_after_ttl_without_use(clock):
    store = make_store(clock)
    store.save(result("a"))

    clock.now += 59
    assert store.get("a") is not None
    clock.now += 61  # 61 s since the read above
    assert store.get("a") is None


def test_reading_a_session_keeps_it_alive(clock):
    store = make_store(clock)
    store.save(result("a"))
    for _ in range(5):
        clock.now += 50
        assert store.get("a") is not None  # 250 s after saving, still here


def test_least_recently_used_session_is_dropped_at_the_cap(clock):
    store = make_store(clock, ttl=3600, cap=2)
    store.save(result("a"))
    store.save(result("b"))
    store.get("a")  # same clock tick: use order alone decides that "b" is least recent
    store.save(result("c"))

    assert store.get("a") is not None
    assert store.get("b") is None
    assert store.get("c") is not None
    assert len(store) == 2


def test_expired_sessions_are_not_counted(clock):
    store = make_store(clock)
    store.save(result("a"))
    store.save(result("b"))
    clock.now += 61
    assert len(store) == 0


def test_sessions_survive_a_restart(clock, tmp_path):
    path = tmp_path / "ada.sqlite3"
    first = make_store(clock, path=path)
    first.save(result("a", cleaned_csv=b"x,y\n1,2\n"))
    first.close()

    reopened = make_store(clock, path=path)  # a new process would do exactly this
    restored = reopened.get("a")

    assert restored is not None
    assert restored.filename == "f.csv"
    assert restored.cleaned_csv == b"x,y\n1,2\n"


def test_expiry_counts_time_spent_while_the_server_was_down(clock, tmp_path):
    path = tmp_path / "ada.sqlite3"
    first = make_store(clock, path=path)
    first.save(result("a"))
    first.close()

    clock.now += 120  # the server was off for two minutes
    assert make_store(clock, path=path).get("a") is None


def test_use_order_continues_across_a_restart(clock, tmp_path):
    path = tmp_path / "ada.sqlite3"
    first = make_store(clock, path=path, ttl=3600, cap=2)
    first.save(result("a"))
    first.save(result("b"))
    first.close()

    second = make_store(clock, path=path, ttl=3600, cap=2)
    second.get("a")
    second.save(result("c"))  # "b" is least recent, even though the counter restarted
    assert second.get("b") is None
    assert second.get("a") is not None


def test_a_result_saved_by_an_older_version_is_dropped_not_crashed_on(clock, tmp_path):
    path = tmp_path / "ada.sqlite3"
    make_store(clock, path=path).save(result("a"))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE sessions SET result_json = ? WHERE id = 'a'", ('{"session_id": "a"}',))

    store = make_store(clock, path=path)
    assert store.get("a") is None
    assert len(store) == 0


def test_expired_session_404_tells_the_user_what_to_do(client):
    res = client.get("/api/sessions/long-gone")
    assert res.status_code == 404
    assert "upload the file again" in res.json()["detail"]


def test_cleaned_csv_is_still_downloadable_after_the_round_trip(client, sample_csv_bytes):
    session_id = client.post(
        "/api/upload", files={"file": ("sales_sample.csv", sample_csv_bytes, "text/csv")}
    ).json()["session_id"]
    res = client.get(f"/api/sessions/{session_id}/cleaned.csv")
    assert res.status_code == 200
    assert res.content.count(b"\n") == 32  # header plus 31 rows
