import pytest

from app.models.schemas import AnalysisResult, LlamaExplanation
from app.session_store import SessionStore


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def result(session_id: str) -> AnalysisResult:
    return AnalysisResult(
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
        llama=LlamaExplanation(dataset_overview="", chart_explanations=[], analysis_summary="", recommendations=[]),
        preview_rows=[],
        cleaned_preview_rows=[],
    )


@pytest.fixture
def clock():
    return FakeClock()


def test_session_expires_after_ttl_without_use(clock):
    store = SessionStore(ttl_seconds=60, max_sessions=10, clock=clock)
    store.save(result("a"))

    clock.now += 59
    assert store.get("a") is not None
    clock.now += 61  # 61 s since the read above
    assert store.get("a") is None


def test_reading_a_session_keeps_it_alive(clock):
    store = SessionStore(ttl_seconds=60, max_sessions=10, clock=clock)
    store.save(result("a"))
    for _ in range(5):
        clock.now += 50
        assert store.get("a") is not None  # 250 s after saving, still here


def test_least_recently_used_session_is_dropped_at_the_cap(clock):
    store = SessionStore(ttl_seconds=3600, max_sessions=2, clock=clock)
    store.save(result("a"))
    store.save(result("b"))
    store.get("a")  # "b" is now the least recently used
    store.save(result("c"))

    assert store.get("a") is not None
    assert store.get("b") is None
    assert store.get("c") is not None
    assert len(store) == 2


def test_expired_sessions_are_not_counted(clock):
    store = SessionStore(ttl_seconds=60, max_sessions=10, clock=clock)
    store.save(result("a"))
    store.save(result("b"))
    clock.now += 61
    assert len(store) == 0


def test_expired_session_404_tells_the_user_what_to_do(client):
    res = client.get("/api/sessions/long-gone")
    assert res.status_code == 404
    assert "upload the file again" in res.json()["detail"]
