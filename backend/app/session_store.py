"""Stored analysis results, kept in SQLite so they survive a restart.

SQLite ships with Python, so persistence needs no database server. Each
session is one row: the result as JSON, plus the cleaned CSV for download.
Two limits keep the file from growing without bound:

- a session expires after ADA_SESSION_TTL_MINUTES without being used, and
- at most ADA_MAX_SESSIONS are kept; the least recently used goes first.

Times are wall-clock (time.time) rather than monotonic, because they have to
mean the same thing after the process restarts.
"""

import itertools
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from app.config import settings
from app.models.schemas import AnalysisResult

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    created_at  REAL NOT NULL,
    last_used   REAL NOT NULL,
    -- Breaks ties between sessions used in the same clock tick, so eviction order is exact.
    use_seq     INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    cleaned_csv BLOB
);
CREATE INDEX IF NOT EXISTS sessions_by_last_use ON sessions (last_used, use_seq);
"""


class SessionStore:
    def __init__(
        self,
        *,
        path: str | Path,
        ttl_seconds: float,
        max_sessions: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._clock = clock
        self._lock = threading.Lock()

        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the event loop and the worker threads, guarded by the lock.
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.executescript(_SCHEMA)
        last_seq = self._db.execute("SELECT COALESCE(MAX(use_seq), 0) FROM sessions").fetchone()[0]
        self._seq = itertools.count(last_seq + 1)

    def save(self, result: AnalysisResult) -> None:
        now = self._clock()
        with self._lock:
            self._drop_expired(now)
            self._db.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    result.session_id,
                    result.filename,
                    now,
                    now,
                    next(self._seq),
                    result.model_dump_json(),
                    result.cleaned_csv,
                ),
            )
            self._db.execute(
                """DELETE FROM sessions WHERE id NOT IN (
                       SELECT id FROM sessions ORDER BY last_used DESC, use_seq DESC LIMIT ?
                   )""",
                (self.max_sessions,),
            )

    def get(self, session_id: str) -> AnalysisResult | None:
        """The result if it exists and hasn't expired. Reading it counts as use."""
        now = self._clock()
        with self._lock:
            self._drop_expired(now)
            row = self._db.execute(
                "SELECT result_json, cleaned_csv FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row is None:
                return None
            try:
                result = AnalysisResult.model_validate_json(row[0])
            except ValidationError:
                # Saved by an older version whose result shape no longer matches.
                logger.warning("Dropping session %s: stored result no longer matches the schema", session_id)
                self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                return None
            self._db.execute(
                "UPDATE sessions SET last_used = ?, use_seq = ? WHERE id = ?",
                (now, next(self._seq), session_id),
            )
        result._cleaned_csv = row[1]
        return result

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._db.execute("DELETE FROM sessions WHERE id = ?", (session_id,)).rowcount > 0

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired(self._clock())
            return int(self._db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _drop_expired(self, now: float) -> None:
        self._db.execute("DELETE FROM sessions WHERE last_used <= ?", (now - self.ttl_seconds,))


store = SessionStore(
    path=settings.database_path,
    ttl_seconds=settings.session_ttl_minutes * 60,
    max_sessions=settings.max_sessions,
)


def save(result: AnalysisResult) -> None:
    store.save(result)


def get(session_id: str) -> AnalysisResult | None:
    return store.get(session_id)


def delete(session_id: str) -> bool:
    return store.delete(session_id)
