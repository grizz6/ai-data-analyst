"""In-memory store for analysis results, bounded in time and size.

Results are held only in this process, so a restart loses them. Two limits
keep a long-running server from growing without bound:

- a session expires after ADA_SESSION_TTL_MINUTES without being used, and
- at most ADA_MAX_SESSIONS are kept; the least recently used goes first.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from app.config import settings
from app.models.schemas import AnalysisResult


@dataclass
class _Entry:
    result: AnalysisResult
    last_used: float


class SessionStore:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_sessions: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def save(self, result: AnalysisResult) -> None:
        with self._lock:
            self._drop_expired()
            self._entries[result.session_id] = _Entry(result, self._clock())
            self._entries.move_to_end(result.session_id)
            while len(self._entries) > self.max_sessions:
                self._entries.popitem(last=False)

    def get(self, session_id: str) -> AnalysisResult | None:
        """The result if it exists and hasn't expired. Reading it counts as use."""
        with self._lock:
            self._drop_expired()
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            entry.last_used = self._clock()
            self._entries.move_to_end(session_id)
            return entry.result

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._entries.pop(session_id, None) is not None

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired()
            return len(self._entries)

    def _drop_expired(self) -> None:
        cutoff = self._clock() - self.ttl_seconds
        # Entries are kept in order of last use, so expired ones are at the front.
        while self._entries:
            oldest_id, oldest = next(iter(self._entries.items()))
            if oldest.last_used > cutoff:
                break
            del self._entries[oldest_id]


store = SessionStore(
    ttl_seconds=settings.session_ttl_minutes * 60,
    max_sessions=settings.max_sessions,
)


def save(result: AnalysisResult) -> None:
    store.save(result)


def get(session_id: str) -> AnalysisResult | None:
    return store.get(session_id)


def delete(session_id: str) -> bool:
    return store.delete(session_id)
