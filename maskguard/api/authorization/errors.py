"""Phase 10.3 §17/§18: authorization errors, same unified `ApiError`
format Phase 10.2's auth errors already use — no separate error
architecture introduced."""
from __future__ import annotations

from fastapi import status

from ..errors import ApiError


class AuthorizationDeniedError(ApiError):
    """§17: 403 — an authenticated identity exists but lacks the required
    permission. Distinct from `AuthenticationRequiredError` (401, no
    identity at all) — see `maskguard.api.auth.errors`.

    §18: deliberately a single generic message, never naming which
    permission/role was required — a 403 must not tell an attacker
    "you need SecurityAdministrator." The actual permission checked is
    logged server-side only (`dependencies.py`), tagged with request_id."""

    status_code = status.HTTP_403_FORBIDDEN
    code = "AUTHORIZATION_DENIED"

    def __init__(self) -> None:
        super().__init__("You are not authorized to perform this operation.")
