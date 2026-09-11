"""Phase 10.2 §3/§38/§41/§45: OIDC + session configuration. Provider-agnostic
(standard OIDC discovery, §3 — no provider-specific branches) and isolated
from MaskGuard Core.

Configuration is env-driven, following the exact pattern Phase 9 already
established in `maskguard/api/config.py` (`_int_env`/`_secret_env`) — no
duplicate configuration system introduced (§71).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from ..config import _int_env, _secret_env

#: Phase 10.2 §41/§39: values a careless operator might paste in and that
#: must never be treated as "configured" — reuses the exact class of check
#: Phase 9's review-token secret validation already applies (§39/§41).
_INSECURE_PLACEHOLDER_VALUES = frozenset(
    {"", "changeme", "change-me", "change_me", "default", "secret", "test", "example"}
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _scopes_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return tuple(s.strip() for s in raw.split() if s.strip())


class InsecureAuthConfigError(RuntimeError):
    """Raised at startup (never mid-request) when OIDC is enabled in
    production with missing/insecure configuration — fail CLOSED (§39),
    never silently fall back to a weaker auth mode."""


@dataclass(frozen=True)
class AuthSettings:
    #: Master switch (§0/§39/§94). When False, no auth routes are
    #: registered and every existing endpoint's current (Phase 9)
    #: public/private semantics are completely unchanged (§31) — this
    #: phase must not accidentally make authentication mandatory.
    oidc_enabled: bool = field(default_factory=lambda: _bool_env("OIDC_ENABLED", False))

    #: §6/§12: the ONLY trusted issuer. Never taken from a request, query
    #: parameter, cookie, or header (§12/§58) — always this server-side
    #: configured value.
    issuer: str | None = field(default_factory=lambda: os.environ.get("OIDC_ISSUER") or None)
    client_id: str | None = field(default_factory=lambda: os.environ.get("OIDC_CLIENT_ID") or None)
    #: §38: Docker-secret-file convention, same pattern as
    #: MASKGUARD_REVIEW_TOKEN_SECRET_FILE (Phase 9 §16).
    client_secret: str | None = field(
        default_factory=lambda: _secret_env("OIDC_CLIENT_SECRET_FILE", "OIDC_CLIENT_SECRET")
    )
    #: §44: exact, pre-registered — never dynamically derived from request
    #: headers (§43).
    redirect_uri: str | None = field(default_factory=lambda: os.environ.get("OIDC_REDIRECT_URI") or None)
    #: §45: `profile`/`email` requested because `/api/v1/auth/me` (§82)
    #: and the identity model (§5/§46) actually use display name/email —
    #: not requested speculatively. `offline_access` deliberately never
    #: requested (§18 — no refresh-token persistence in this phase, §17
    #: documents MaskGuard does not need one).
    scopes: tuple[str, ...] = field(
        default_factory=lambda: _scopes_env("OIDC_SCOPES", ("openid", "profile", "email"))
    )
    #: §14: conservative default (2 minutes). Documented maximum reasonable
    #: override: 300s (5 minutes) — see docs/authentication-implementation.md.
    #: Applies to `exp`/`nbf`/`iat` validation (§14).
    clock_skew_seconds: int = field(default_factory=lambda: _int_env("OIDC_CLOCK_SKEW_SECONDS", 120))
    #: §59: bounded HTTP timeouts for discovery/token/JWKS calls — never
    #: indefinite.
    http_connect_timeout_seconds: float = field(
        default_factory=lambda: float(os.environ.get("OIDC_HTTP_CONNECT_TIMEOUT_SECONDS", "5"))
    )
    http_read_timeout_seconds: float = field(
        default_factory=lambda: float(os.environ.get("OIDC_HTTP_READ_TIMEOUT_SECONDS", "5"))
    )

    # --- Session (§19-23) ---------------------------------------------------
    session_idle_timeout_seconds: int = field(
        default_factory=lambda: _int_env("SESSION_IDLE_TIMEOUT_SECONDS", 30 * 60)
    )
    session_absolute_timeout_seconds: int = field(
        default_factory=lambda: _int_env("SESSION_ABSOLUTE_TIMEOUT_SECONDS", 8 * 60 * 60)
    )
    #: §76: bounds in-memory session-store growth (this phase's
    #: process-local store, §20 — NOT a substitute for Phase 10.5 rate
    #: limiting, documented as such).
    max_sessions: int = field(default_factory=lambda: _int_env("SESSION_MAX_COUNT", 10_000))
    #: §77: bounds the pending-login-transaction store the same way.
    max_pending_transactions: int = field(default_factory=lambda: _int_env("OIDC_MAX_PENDING_TRANSACTIONS", 10_000))
    #: §77: a login transaction (state/nonce/PKCE) not completed within
    #: this window is no longer valid — bounded, short-lived (§8).
    transaction_ttl_seconds: int = field(default_factory=lambda: _int_env("OIDC_TRANSACTION_TTL_SECONDS", 600))

    #: §42: Secure=False is a DEVELOPMENT-ONLY override for plain-HTTP
    #: local testing — production always forces True regardless of this
    #: value (see validate_production_auth_config below, fail-closed).
    cookie_secure_override: bool = field(default_factory=lambda: _bool_env("AUTH_COOKIE_SECURE", True))
    #: §23: an opaque cookie name — reveals nothing about the mechanism.
    session_cookie_name: str = "mg_sess"
    transaction_cookie_name: str = "mg_txn"


@lru_cache
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


def validate_production_auth_config(environment: str, settings: AuthSettings) -> None:
    """Phase 10.2 §39/§41: fail CLOSED at startup — never lazily on first
    login attempt — if OIDC is enabled in production with incomplete or
    insecure configuration. Mirrors `maskguard.api.config.validate_production_secret`'s
    existing pattern exactly (Phase 9 §17)."""
    if not settings.oidc_enabled:
        return  # auth not enabled at all — nothing to validate (§0/§31)
    if environment != "production":
        return  # development/test: incomplete OIDC config is a dev-time concern, not fail-closed here

    missing = []
    if not settings.issuer:
        missing.append("OIDC_ISSUER")
    if not settings.client_id:
        missing.append("OIDC_CLIENT_ID")
    if not settings.redirect_uri:
        missing.append("OIDC_REDIRECT_URI")
    if missing:
        raise InsecureAuthConfigError(
            "OIDC_ENABLED=true in production requires " + ", ".join(missing) + " to be set — "
            "refusing to start with incomplete authentication configuration."
        )
    if not str(settings.issuer).startswith("https://"):
        raise InsecureAuthConfigError("OIDC_ISSUER must be an https:// URL in production.")
    if not str(settings.redirect_uri).startswith("https://"):
        raise InsecureAuthConfigError("OIDC_REDIRECT_URI must be an https:// URL in production.")
    if settings.client_id.strip().lower() in _INSECURE_PLACEHOLDER_VALUES:
        raise InsecureAuthConfigError("OIDC_CLIENT_ID is an obviously-insecure placeholder value.")
    if not settings.cookie_secure_override:
        raise InsecureAuthConfigError(
            "AUTH_COOKIE_SECURE=false is not permitted in production — session cookies "
            "must always be Secure (HTTPS-only) in production."
        )
