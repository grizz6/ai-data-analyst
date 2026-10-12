"""Keep a free Render service from going to sleep.

Render's free plan stops a web service after 15 minutes without incoming
requests, and the next visitor waits about a minute for it to start again.
While the app runs, this sends a request to its own public address every few
minutes. It goes out to the internet and back in through Render's front door,
so it counts as a visit. A scheduled job somewhere else can't promise that:
GitHub, for one, delays and skips frequent scheduled runs.

The address comes from ADA_KEEP_AWAKE_URL, or from RENDER_EXTERNAL_URL, which
Render sets on every web service. Neither is set locally or in tests, so this
only runs on Render.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

HEALTH_PATH = "/api/health"
REQUEST_TIMEOUT_SECONDS = 30


def keep_awake_url() -> str | None:
    """The health-check address to request, or None when there's nothing to keep awake."""
    base = (settings.keep_awake_url or os.environ.get("RENDER_EXTERNAL_URL", "")).strip().rstrip("/")
    if not base.startswith("https://") or settings.keep_awake_minutes <= 0:
        return None
    return base + HEALTH_PATH


async def keep_awake(
    url: str,
    interval_seconds: float,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rounds: int | None = None,
) -> None:
    """Request `url` every `interval_seconds` until cancelled. A failed request is logged, never raised."""
    done = 0
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, transport=transport) as client:
        while rounds is None or done < rounds:
            await sleep(interval_seconds)
            try:
                response = await client.get(url, headers={"User-Agent": "keep-awake"})
                if response.status_code != 200:
                    logger.warning("keep-awake: %s answered %s", url, response.status_code)
            except httpx.HTTPError as exc:
                logger.warning("keep-awake: request to %s failed: %s", url, exc)
            done += 1
