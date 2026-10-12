"""The app keeps its own Render service awake, and does nothing anywhere else."""

import asyncio

import httpx

from app import keep_awake
from app.config import settings


def test_off_unless_a_public_https_address_is_known(monkeypatch):
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setattr(settings, "keep_awake_url", "")
    assert keep_awake.keep_awake_url() is None
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "http://insecure.example")
    assert keep_awake.keep_awake_url() is None


def test_uses_renders_address_or_an_override(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://ai-data-analyst.onrender.com/")
    monkeypatch.setattr(settings, "keep_awake_url", "")
    assert keep_awake.keep_awake_url() == "https://ai-data-analyst.onrender.com/api/health"
    monkeypatch.setattr(settings, "keep_awake_url", "https://example.org")
    assert keep_awake.keep_awake_url() == "https://example.org/api/health"
    monkeypatch.setattr(settings, "keep_awake_minutes", 0)
    assert keep_awake.keep_awake_url() is None


def test_requests_on_every_round_and_survives_failures():
    calls: list[str] = []
    waits: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 2:
            raise httpx.ConnectError("down")
        return httpx.Response(503 if len(calls) == 3 else 200)

    async def no_sleep(seconds: float) -> None:
        waits.append(seconds)

    asyncio.run(
        keep_awake.keep_awake(
            "https://site.test/api/health", 600, transport=httpx.MockTransport(handle), sleep=no_sleep, rounds=4
        )
    )
    assert calls == ["https://site.test/api/health"] * 4
    assert waits == [600] * 4


def test_app_starts_the_pings_on_render_and_stops_them_on_shutdown(client, monkeypatch):
    started: list[tuple[str, float]] = []
    stopped = asyncio.Event()

    async def fake_keep_awake(url: str, interval: float) -> None:
        started.append((url, interval))
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stopped.set()
            raise

    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://ai-data-analyst.onrender.com")
    monkeypatch.setattr(settings, "keep_awake_minutes", 10)
    monkeypatch.setattr(keep_awake, "keep_awake", fake_keep_awake)
    with client:
        assert client.get("/api/health").status_code == 200
    assert started == [("https://ai-data-analyst.onrender.com/api/health", 600)]
    assert stopped.is_set()


def test_app_starts_without_pings_elsewhere(client, monkeypatch):
    called = []
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setattr(keep_awake, "keep_awake", lambda *a: called.append(a))
    with client:
        assert client.get("/api/health").status_code == 200
    assert called == []
