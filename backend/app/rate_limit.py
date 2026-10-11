"""Per-visitor request limits, so one person can't use up the server or the LLM quota.

Each limit is a sliding window: a visitor may make at most N requests of a kind
in any one-hour span. Counts live in memory, so they reset when the process
restarts and aren't shared between several server processes. That suits the
single-process deployment this app is built for.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

WINDOW_SECONDS = 3600.0
# Visitors seen in the last hour; past this, the oldest are forgotten so memory stays bounded.
MAX_TRACKED_VISITORS = 10_000


class RateLimiter:
    def __init__(self, *, window_seconds: float = WINDOW_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int) -> float | None:
        """Record a request from `key`. None if allowed, else seconds until one is.

        A limit of 0 or less means unlimited. Refused requests aren't recorded,
        so retrying while blocked doesn't push the wait further out.
        """
        if limit <= 0:
            return None
        now = self._clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                if len(self._hits) >= MAX_TRACKED_VISITORS:
                    self._forget_idle(now)
                hits = self._hits[key] = deque()
            while hits and hits[0] <= now - self.window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return hits[0] + self.window_seconds - now
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _forget_idle(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
        # Everyone is still active: drop the visitors whose last request is oldest.
        if len(self._hits) >= MAX_TRACKED_VISITORS:
            by_last_hit = sorted(self._hits, key=lambda k: self._hits[k][-1])
            for key in by_last_hit[: len(self._hits) - MAX_TRACKED_VISITORS + 1]:
                del self._hits[key]


def visitor_address(
    direct_peer: str | None,
    forwarded_for: str | None,
    trusted_hops: int,
    edge_client_ip: str | None = None,
) -> str:
    """The visitor's IP address, as far as it can be trusted.

    edge_client_ip is the value of a header the hosting edge overwrites with
    the visitor's address (see ADA_CLIENT_IP_HEADER); when present it wins.

    Each trusted proxy appends the address it received the request from, so
    with N trusted proxies the Nth entry from the right is the visitor's.
    Entries further left were written by the client and could be anything.
    """
    if edge_client_ip and edge_client_ip.strip():
        return edge_client_ip.strip()
    if trusted_hops > 0 and forwarded_for:
        entries = [e.strip() for e in forwarded_for.split(",") if e.strip()]
        if entries:
            return entries[-min(trusted_hops, len(entries))]
    return direct_peer or "unknown"


def retry_after_header(wait_seconds: float) -> str:
    return str(max(1, math.ceil(wait_seconds)))


def describe_wait(wait_seconds: float) -> str:
    minutes = max(1, math.ceil(wait_seconds / 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


uploads = RateLimiter()
questions = RateLimiter()
charts = RateLimiter()
models = RateLimiter()
