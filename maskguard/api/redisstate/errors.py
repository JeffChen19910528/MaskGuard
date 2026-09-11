"""Phase 10.6 §18/§30/§41/§97: the ONE HTTP-facing error for "a required
shared-state dependency is unavailable" — reuses the existing unified
error format, never a 200/401/403 masquerading as a normal outcome."""
from __future__ import annotations

from fastapi import status

from ..errors import ApiError


class DependencyUnavailableError(ApiError):
    """§97: 503, not 401/403/429/200 — a Redis-backed session/replay/
    rate-limit check that could not be evaluated is a DEPENDENCY failure,
    not "you are unauthenticated" (401), "you are forbidden" (403), or
    "you are rate limited" (429), and never a silent success (200). This
    is what "fails safely" (§18/§30/§41) means concretely: the protected
    operation does not happen, and the client is told exactly why in
    general terms — never a Redis hostname/exception/stack trace (§98)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "DEPENDENCY_UNAVAILABLE"

    def __init__(self, detail: str = "A required service is temporarily unavailable.") -> None:
        super().__init__(detail)
