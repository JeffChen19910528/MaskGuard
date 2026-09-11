"""Phase 10.2 §5/§46/§47: internal identity/session representations.

`AuthenticatedIdentity` intentionally carries ONLY what MaskGuard actually
uses — never the full ID-token claim set, never an access/refresh/ID
token (§5/§17/§18/§80). The stable identity key is `issuer + subject`
(§47), never email (which can change).
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Everything MaskGuard needs to know about an authenticated caller —
    nothing more. No access/refresh/ID token, no arbitrary IdP claims."""

    subject: str  #: `sub` claim — stable within one issuer
    issuer: str  #: `iss` claim — the trusted, configured issuer (§12)
    authenticated_at: float  #: unix timestamp of the original login
    provider: str  #: a short label for which configured provider this came from (today: always "oidc" — a single configured issuer, §3)
    email: str | None = None
    display_name: str | None = None

    @property
    def identity_key(self) -> str:
        """`issuer + subject` (§47) — the stable security identity. NEVER
        email, which is not treated as immutable identity."""
        return f"{self.issuer}|{self.subject}"


@dataclass
class PendingAuthTransaction:
    """One in-flight `/auth/login` -> `/auth/callback` round trip (§8/§9/§10/§79).
    Consumed exactly once (§79) — `session.py`'s transaction store deletes
    the entry on first successful lookup, so a replayed callback with the
    same transaction id finds nothing."""

    transaction_id: str
    state: str
    nonce: str
    code_verifier: str  #: PKCE (§10) — never logged, never exposed to the browser beyond the opaque transaction cookie
    created_at: float
    #: Where to send the browser after a successful login (§26 — validated
    #: against an allowlist of relative paths before use, never an
    #: arbitrary external URL).
    return_path: str = "/"

    def is_expired(self, ttl_seconds: int, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) - self.created_at > ttl_seconds


@dataclass
class SessionRecord:
    """Server-side session state (§19/§20). The browser only ever holds
    the opaque `session_id` via the session cookie — everything below
    stays server-side."""

    session_id: str
    identity: AuthenticatedIdentity
    created_at: float
    last_seen_at: float
    absolute_expires_at: float

    def is_expired(self, idle_timeout_seconds: int, now: float | None = None) -> bool:
        t = now if now is not None else time.time()
        if t > self.absolute_expires_at:
            return True
        if t - self.last_seen_at > idle_timeout_seconds:
            return True
        return False
