from app.config import settings
from app.rate_limit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_up_to_the_limit_then_reports_the_wait():
    clock = FakeClock()
    limiter = RateLimiter(window_seconds=3600, clock=clock)
    assert [limiter.check("a", 3) for _ in range(3)] == [None, None, None]

    clock.now += 600
    assert limiter.check("a", 3) == 3000  # the first request leaves the window in 50 minutes
    assert limiter.check("b", 3) is None  # other visitors are counted separately


def test_limiter_window_slides_and_refusals_are_not_counted():
    clock = FakeClock()
    limiter = RateLimiter(window_seconds=60, clock=clock)
    limiter.check("a", 1)
    for _ in range(5):
        clock.now += 10
        assert limiter.check("a", 1) is not None
    clock.now += 10  # 60 s after the only counted request
    assert limiter.check("a", 1) is None


def test_zero_limit_means_unlimited():
    limiter = RateLimiter()
    assert all(limiter.check("a", 0) is None for _ in range(100))


def test_uploads_over_the_hourly_limit_get_429(client, monkeypatch, sample_csv_bytes):
    monkeypatch.setattr(settings, "uploads_per_hour", 2)
    files = {"file": ("sales.csv", sample_csv_bytes, "text/csv")}
    assert [client.post("/api/upload", files=files).status_code for _ in range(2)] == [200, 200]

    res = client.post("/api/upload", files=files)
    assert res.status_code == 429
    assert int(res.headers["Retry-After"]) > 0
    assert "limit is 2 per hour" in res.json()["detail"]


def test_questions_are_limited_separately_from_uploads(client, monkeypatch, sample_csv_bytes):
    monkeypatch.setattr(settings, "uploads_per_hour", 1)
    monkeypatch.setattr(settings, "questions_per_hour", 2)
    session_id = client.post("/api/upload", files={"file": ("s.csv", sample_csv_bytes, "text/csv")}).json()[
        "session_id"
    ]

    ask = lambda: client.post(f"/api/sessions/{session_id}/ask", json={"question": "What stands out?"})  # noqa: E731
    assert [ask().status_code for _ in range(3)] == [200, 200, 429]
    # Reading results and downloads are never limited.
    assert client.get(f"/api/sessions/{session_id}").status_code == 200
    assert client.get(f"/api/sessions/{session_id}/report").status_code == 200
