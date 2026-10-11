"""Limits on heavy work, so one large file can't take the server down for everyone.

An analysis of a 10 MB file can use a few hundred MB of memory, and the free
hosting plans this app targets have 512 MB in total. Running analyses one at
a time keeps the peak to a single file; anyone else waits their turn, and
after ADA_ANALYSIS_QUEUE_WAIT_SECONDS gets a "busy, try again" message
instead of a crash that would also wipe everyone's stored results.

The slot is a thread semaphore because the work it guards runs in worker
threads, and a thread can wait on it without holding up the event loop.
"""

import threading
from collections.abc import Callable

from app.config import settings


class BusyError(RuntimeError):
    """Every slot stayed taken for the whole wait."""


_slots = threading.BoundedSemaphore(max(1, settings.max_concurrent_analyses))


def run_in_slot[**P, T](fn: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Run fn once a slot is free. Call it from a worker thread, never the event loop."""
    if not _slots.acquire(timeout=settings.analysis_queue_wait_seconds):
        raise BusyError
    try:
        return fn(*args, **kwargs)
    finally:
        _slots.release()


def busy_detail() -> str:
    return "The server is busy with other files right now. Please try again in a minute."
