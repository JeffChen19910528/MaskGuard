"""Bounded concurrent Core processing (Phase 8.4 §21-23 — "one of the most
important Phase 8.4 items").

Preserves the existing architecture exactly: ONE shared `Pipeline`/OCR
engine instance for the whole process (`MaskGuardService`, Phase 8.1 §20) —
this module never creates a second engine or a per-request Pipeline. It
only bounds how many of that ONE Pipeline's `.process()`-equivalent calls
may run at once, via a plain counter guarded by an `asyncio.Lock` (not
`asyncio.Semaphore.acquire()`, which BLOCKS/queues the caller until a slot
frees — Phase 8.4 §21 explicitly wants an over-capacity request to fail
FAST with `429`, never queue indefinitely).

Timeout/concurrency interaction (§23, read carefully): Python cannot force-
kill a synchronous worker thread. When `run_with_timeout` (routes/_shared.py)
gives up waiting on a slow job, the underlying thread keeps running to
completion in the background — this was already true and documented before
Phase 8.4. What Phase 8.4 adds: the concurrency slot that phantom worker
holds is NOT released just because the HTTP response already returned 504
— it stays held until the worker's thread genuinely finishes (via
`asyncio.Task.add_done_callback`, decoupled from whatever the caller's
`wait_for` already gave up on). This is what actually bounds worst-case
concurrent CPU usage: a flood of timeout-inducing requests can occupy at
most `max_concurrent_jobs` phantom workers, never more, even though each
individual HTTP call already returned.
"""
from __future__ import annotations

import asyncio


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int) -> None:
        self._max = max(1, max_concurrent)
        self._count = 0
        self._lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        return self._max

    async def try_acquire(self) -> bool:
        """Non-blocking: returns False immediately (never waits/queues) if
        already at capacity."""
        async with self._lock:
            if self._count >= self._max:
                return False
            self._count += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def active_count(self) -> int:
        return self._count
