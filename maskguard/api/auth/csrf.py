"""Phase 10.2 §24/§25/§29: CSRF protection for cookie-authenticated,
state-changing requests. `SameSite=Lax` (cookies.py) already blocks most
cross-site POST/PUT/PATCH/DELETE from carrying the session cookie, but
per §24 ("do not assume SameSite alone is sufficient for all
deployments") this module adds an explicit Origin check as a second,
independent layer for any endpoint that changes state using the session
cookie (today: only `/api/v1/auth/logout`, §29 — no existing
analyze/redact/verify/review endpoint requires a session in this phase,
§31).
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request

from .errors import CsrfValidationError


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def validate_same_origin(request: Request, *, expected_origins: tuple[str, ...]) -> None:
    """§25: validates the `Origin` header (falling back to `Referer` only
    if `Origin` is entirely absent — some legitimate same-origin requests
    omit it) against an explicit allowlist of trusted origins. Missing AND
    unparseable both fail closed (§25: "define behavior for missing
    Origin" — this implementation treats a missing Origin as REJECTED,
    the stricter of the two reasonable choices, since a same-origin
    browser POST always sends one)."""
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            origin = _origin_of(referer)
    if not origin or origin not in expected_origins:
        raise CsrfValidationError("Request origin could not be verified.")
