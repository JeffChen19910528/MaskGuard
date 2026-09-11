"""Small helpers shared by routes/images.py and routes/review.py — request
timeout/concurrency/threadpool offload and whitelisted-field-only request
logging (Phase 8.1 §15/§21, Phase 8.4 §21-23). No Detection/Risk/Policy/
Redaction/Verification logic.
"""
from __future__ import annotations

import asyncio
import logging

import anyio
from fastapi import Request

from ..concurrency import ConcurrencyLimiter
from ..config import ApiSettings
from ..errors import ProcessingTimeoutError, TooManyConcurrentJobsError

logger = logging.getLogger("maskguard.api")


async def run_with_timeout(func, *args, settings: ApiSettings, limiter: ConcurrencyLimiter):
    """Bounds concurrent Core work (§21/§22) and applies the configured
    processing timeout (§23/§24). A request that would exceed
    `max_concurrent_jobs` is refused immediately with `429` — never queued.

    Timeout semantics (§23): `asyncio.wait_for` over `asyncio.shield(task)`
    means a timeout only stops THIS request from waiting any longer — the
    underlying worker thread is NOT cancelled (Python cannot force-kill a
    running thread) and keeps executing in the background. Its concurrency
    slot is released only when it actually finishes (`add_done_callback`),
    not when this function gives up waiting — see concurrency.py's
    docstring for why that distinction is what actually bounds worst-case
    concurrent CPU usage under repeated timeouts.
    """
    if not await limiter.try_acquire():
        raise TooManyConcurrentJobsError(
            f"Server is at capacity ({limiter.max_concurrent} concurrent jobs); please retry shortly."
        )

    task: asyncio.Task = asyncio.ensure_future(anyio.to_thread.run_sync(func, *args))

    def _release(_task: asyncio.Task) -> None:
        asyncio.ensure_future(limiter.release())

    task.add_done_callback(_release)

    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=settings.processing_timeout_seconds)
    except asyncio.TimeoutError:
        raise ProcessingTimeoutError(
            f"Processing did not complete within {settings.processing_timeout_seconds}s."
        ) from None


def log_request(request: Request, route: str, *, duration_s: float, file_size: int, **extra) -> None:
    # Deliberately whitelisted fields only — see §15. Never log OCR text,
    # detection values, filenames, review reasons, or any Core-decoded content.
    request_id = getattr(request.state, "request_id", None)
    logger.info(
        "api_request route=%s request_id=%s duration_s=%.3f file_size_bytes=%d %s",
        route,
        request_id,
        duration_s,
        file_size,
        " ".join(f"{k}={v}" for k, v in extra.items()),
    )
