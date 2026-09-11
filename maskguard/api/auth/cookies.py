"""Phase 10.2 §19/§23: cookie set/clear helpers. Cookies carry ONLY an
opaque identifier — never a token, never identity data, never claims
(§19/§23/§80). `HttpOnly`+`Secure`+`SameSite` on every auth cookie.
"""
from __future__ import annotations

from fastapi import Response

from .config import AuthSettings


def set_session_cookie(response: Response, settings: AuthSettings, session_id: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        httponly=True,  # §23: never readable by frontend JS — the frontend must never see this value (§33/§34)
        secure=settings.cookie_secure_override,  # §42: production always True (enforced by validate_production_auth_config)
        samesite="lax",  # §23/§24: Lax allows the OIDC callback's top-level GET redirect to still carry the cookie, while blocking cross-site POST/state-changing requests
        path="/",
        max_age=settings.session_absolute_timeout_seconds,
    )


def clear_session_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/")


def set_transaction_cookie(response: Response, settings: AuthSettings, transaction_id: str) -> None:
    response.set_cookie(
        key=settings.transaction_cookie_name,
        value=transaction_id,
        httponly=True,
        secure=settings.cookie_secure_override,
        samesite="lax",  # must survive the top-level redirect back from the IdP
        path="/",
        max_age=settings.transaction_ttl_seconds,
    )


def clear_transaction_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(key=settings.transaction_cookie_name, path="/")
