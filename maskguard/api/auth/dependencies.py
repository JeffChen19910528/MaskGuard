"""Phase 10.2 §30: FastAPI dependency wiring for the auth module —
constructed once per process (mirrors `maskguard.api.dependencies.get_service`'s
existing pattern), never per-request.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
from fastapi import Cookie, Depends

from .config import AuthSettings, get_auth_settings
from .discovery import JwksKeyProvider, OidcDiscoveryDocument, fetch_discovery_document
from .errors import AuthenticationRequiredError, SessionExpiredError
from .models import AuthenticatedIdentity
from .session import InMemoryPendingTransactionStore, InMemorySessionStore, PendingTransactionStore, SessionStore

#: §94: how long a successfully-fetched discovery document is trusted
#: before a background refresh is attempted — NOT re-fetched on every
#: login (that would make every login latency-dependent on the IdP's
#: discovery endpoint) but also not fetched once and pinned forever
#: (IdPs do occasionally rotate endpoints).
_DISCOVERY_CACHE_SECONDS = 3600


@dataclass
class _DiscoveryCache:
    document: OidcDiscoveryDocument | None = None
    key_provider: JwksKeyProvider | None = None
    fetched_at: float = 0.0


@dataclass
class AuthRuntime:
    settings: AuthSettings
    session_store: SessionStore
    transaction_store: PendingTransactionStore
    http_client: httpx.AsyncClient
    _discovery_cache: _DiscoveryCache = field(default_factory=_DiscoveryCache)

    async def get_discovery(self) -> tuple[OidcDiscoveryDocument, JwksKeyProvider]:
        cache = self._discovery_cache
        now = time.time()
        if cache.document is not None and (now - cache.fetched_at) < _DISCOVERY_CACHE_SECONDS:
            return cache.document, cache.key_provider  # type: ignore[return-value]
        document = await fetch_discovery_document(self.settings, self.http_client)
        key_provider = JwksKeyProvider(
            document.jwks_uri,
            timeout_seconds=self.settings.http_read_timeout_seconds,
        )
        cache.document = document
        cache.key_provider = key_provider
        cache.fetched_at = now
        return document, key_provider


def _build_session_and_transaction_stores(settings: AuthSettings) -> tuple[SessionStore, PendingTransactionStore]:
    """Phase 10.6 §7/§12/§13/§61: Redis-backed when `REDIS_ENABLED=true`
    (cross-instance session/transaction state), else the unchanged Phase
    10.2 in-memory stores. Selected once, at runtime construction — every
    caller (routes.py, authorization/dependencies.py) just calls
    `.get()`/`.create()`/`.delete()`/`.rotate()` and never knows which
    backend is active."""
    from ..redisstate.config import get_redis_settings

    if not get_redis_settings().enabled:
        return (
            InMemorySessionStore(max_sessions=settings.max_sessions),
            InMemoryPendingTransactionStore(max_transactions=settings.max_pending_transactions),
        )
    from ..redisstate.client import get_redis_client_and_namespace
    from .session import RedisPendingTransactionStore, RedisSessionStore

    client, namespace = get_redis_client_and_namespace()
    return RedisSessionStore(client, namespace), RedisPendingTransactionStore(client, namespace)


@lru_cache
def get_auth_runtime() -> AuthRuntime:
    settings = get_auth_settings()
    session_store, transaction_store = _build_session_and_transaction_stores(settings)
    return AuthRuntime(
        settings=settings,
        session_store=session_store,
        transaction_store=transaction_store,
        http_client=httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.http_connect_timeout_seconds,
                read=settings.http_read_timeout_seconds,
                write=settings.http_read_timeout_seconds,
                pool=settings.http_connect_timeout_seconds,
            )
        ),
    )


def _get_session_record(runtime: AuthRuntime, session_cookie: str):
    """Phase 10.6 §18/§95/§97: the ONE place `session_store.get()`'s
    Redis failure is translated — `RedisUnavailableError` NEVER becomes
    "no session found" (that would be fail-open authentication, §95);
    it becomes an explicit `503 DEPENDENCY_UNAVAILABLE`, distinct from
    both "authenticated" and "not authenticated."""
    from ..redisstate.client import RedisUnavailableError
    from ..redisstate.errors import DependencyUnavailableError

    try:
        return runtime.session_store.get(session_cookie, runtime.settings.session_idle_timeout_seconds)
    except RedisUnavailableError as exc:
        raise DependencyUnavailableError("Session could not be verified; please retry shortly.") from exc


def get_current_identity(
    session_cookie: str | None = Cookie(default=None, alias="mg_sess"),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AuthenticatedIdentity:
    """§30: the ONLY way a route should learn "who is this caller." Reads
    and validates the session; returns the identity or raises 401 — never
    403 for plain absence (§30), never a role/permission concept (that is
    Phase 10.3, not here)."""
    if not session_cookie:
        raise AuthenticationRequiredError()
    record = _get_session_record(runtime, session_cookie)
    if record is None:
        raise SessionExpiredError()
    return record.identity


def get_optional_identity(
    session_cookie: str | None = Cookie(default=None, alias="mg_sess"),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AuthenticatedIdentity | None:
    """Used by `/api/v1/auth/me` (§82), which reports authentication
    status rather than requiring it (200 either way, never 401 for
    "not logged in" on a status-probe endpoint). Phase 10.6: a Redis
    failure still raises `DependencyUnavailableError` (503) here too —
    silently reporting `{"authenticated": false}` during an outage would
    misrepresent a logged-in user's actual state (§18/§54's readiness
    distinction: this endpoint should say "I can't tell right now" — not
    a confident, possibly-wrong "no")."""
    if not session_cookie:
        return None
    record = _get_session_record(runtime, session_cookie)
    return record.identity if record else None
