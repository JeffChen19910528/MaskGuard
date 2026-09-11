"""Phase 10.5 §25/§26/§88: the unified `RATE_LIMITED` 429 response —
reuses the EXISTING API error format (`errors.py`), never a second
bespoke error schema."""
from __future__ import annotations

from fastapi import status

from ..errors import ApiError


class RateLimitedError(ApiError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "RATE_LIMITED"

    def __init__(self, retry_after_seconds: int) -> None:
        # §26/§73: no internal key, actor identity, or counter value in
        # the message — a fixed, generic string. §74: Retry-After is
        # always a small positive integer, never negative/absurd.
        bounded_retry_after = max(1, min(int(retry_after_seconds), 3600))
        super().__init__(
            "Too many requests.",
            headers={"Retry-After": str(bounded_retry_after)},
        )
