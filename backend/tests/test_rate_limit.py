import pytest

from app.config import settings
from app.rate_limit import RateLimiter, visitor_address


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


@pytest.mark.parametrize(
    "forwarded, hops, expected",
    [
        (None, 1, "10.0.0.1"),  # no header: the direct peer
        ("203.0.113.7", 0, "10.0.0.1"),  # header ignored unless a proxy is trusted
        ("203.0.113.7", 1, "203.0.113.7"),
        ("6.6.6.6, 203.0.113.7", 1, "203.0.113.7"),  # a spoofed entry on the left is skipped
        ("6.6.6.6, 203.0.113.7, 10.1.1.1", 2, "203.0.113.7"),
        ("203.0.113.7", 3, "203.0.113.7"),  # fewer entries than hops: the leftmost there is
    ],
)
def test_visitor_address_trusts_only_proxy_written_entries(forwarded, hops, expected):
    assert visitor_address("10.0.0.1", forwarded, hops) == expected


def test_behind_a_proxy_each_visitor_gets_their_own_limit(client, monkeypatch, sample_csv_bytes):
    monkeypatch.setattr(settings, "uploads_per_hour", 1)
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    files = {"file": ("sales.csv", sample_csv_bytes, "text/csv")}

    def upload(forwarded: str) -> int:
        return client.post("/api/upload", files=files, headers={"X-Forwarded-For": forwarded}).status_code

    assert upload("203.0.113.7") == 200
    assert upload("198.51.100.4") == 200  # a different visitor
    assert upload("203.0.113.7") == 429
    assert upload("1.2.3.4, 203.0.113.7") == 429  # faking an address in front doesn't help


def test_edge_header_wins_over_forwarded_for():
    assert visitor_address("10.0.0.1", "6.6.6.6, 104.16.0.1", 1, "203.0.113.7") == "203.0.113.7"
    assert visitor_address("10.0.0.1", None, 0, "  ") == "10.0.0.1"  # blank header: fall back


def test_behind_an_edge_header_spoofed_forwarded_for_is_ignored(client, monkeypatch, sample_csv_bytes):
    monkeypatch.setattr(settings, "uploads_per_hour", 1)
    monkeypatch.setattr(settings, "client_ip_header", "true-client-ip")
    files = {"file": ("sales.csv", sample_csv_bytes, "text/csv")}

    def upload(headers: dict[str, str]) -> int:
        return client.post("/api/upload", files=files, headers=headers).status_code

    assert upload({"True-Client-IP": "203.0.113.7"}) == 200
    assert upload({"True-Client-IP": "198.51.100.4"}) == 200
    # Same visitor (the edge always sets the header), whatever X-Forwarded-For says.
    assert upload({"True-Client-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4"}) == 429
