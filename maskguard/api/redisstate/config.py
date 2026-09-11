"""Phase 10.6 §112/§113/§114/§177/§178: Redis configuration. Same
env-driven pattern as every other Phase 10.x config module — no
duplicate configuration system, no hot reload.

There is deliberately NO separate `MULTI_INSTANCE` flag (§113/§114/§177's
"avoid dangerous partial configuration" concern about invalid
REDIS_ENABLED/MULTI_INSTANCE combinations is avoided by not having a
second flag to be inconsistent with): `REDIS_ENABLED` IS the
multi-instance switch. Enabling it swaps session/review-replay/
rate-limit storage to Redis-backed implementations — safe to run with a
single API instance too (nothing breaks), and REQUIRED for correctness
once more than one instance is running behind a load balancer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote

from ..auth.config import _bool_env
from ..config import _int_env, _secret_env


class InsecureRedisConfigError(RuntimeError):
    """§114/§178: fail closed at startup on malformed/incomplete Redis
    configuration — never a silent fallback (e.g. to `localhost`)."""


@dataclass(frozen=True)
class RedisSettings:
    #: §0/§112: master switch. False (default) = every component keeps
    #: its exact Phase 10.2/10.3/10.5 in-memory behavior.
    enabled: bool = field(default_factory=lambda: _bool_env("REDIS_ENABLED", False))
    #: §114: NEVER defaulted to `localhost` — a deployment that enables
    #: Redis but forgets the URL fails startup loudly (`validate_production_redis_config`)
    #: rather than silently talking to nothing/the wrong host.
    url: str | None = field(default_factory=lambda: os.environ.get("REDIS_URL") or None)
    #: §48/§107: prefer a Docker-secret-style `*_FILE` (same convention as
    #: every other Phase 9/10.x secret) — appended to `url` as
    #: `redis://:<password>@host:port/db` if `url` doesn't already embed
    #: credentials. Never committed, logged, or returned by any endpoint.
    password: str | None = field(default_factory=lambda: _secret_env("REDIS_PASSWORD_FILE", "REDIS_PASSWORD"))
    #: §51: every Redis operation is bounded — no infinite network waits.
    socket_timeout_seconds: float = field(default_factory=lambda: float(_int_env("REDIS_SOCKET_TIMEOUT_SECONDS", 2)))
    socket_connect_timeout_seconds: float = field(
        default_factory=lambda: float(_int_env("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS", 2))
    )
    #: §50: bounded connection pool — never unlimited.
    max_connections: int = field(default_factory=lambda: _int_env("REDIS_MAX_CONNECTIONS", 50))
    #: §52/§100: bounded retries — a Redis outage must not become request
    #: amplification. 0 = no retry (fail fast on the first error).
    retry_limit: int = field(default_factory=lambda: _int_env("REDIS_RETRY_LIMIT", 1))
    #: §105/§106: namespace prefix — isolates environments (dev/test/prod)
    #: sharing one Redis instance, and gives every key a clear owner.
    #: `maskguard:<environment>:` — derived from `MASKGUARD_ENV` by
    #: default, overridable for test isolation (`REDIS_NAMESPACE`).
    namespace: str = field(default_factory=lambda: os.environ.get("REDIS_NAMESPACE") or "")

    def resolved_namespace(self, environment: str) -> str:
        return self.namespace or f"maskguard:{environment}:"

    def connection_url(self) -> str:
        """§48: injects the password (if supplied separately from `url`)
        without ever logging or returning it — callers get a ready-to-use
        URL, this is the ONLY place credential material is assembled."""
        if not self.url:
            raise InsecureRedisConfigError("REDIS_URL is not set.")
        if self.password and "@" not in self.url.split("//", 1)[-1]:
            scheme, _, rest = self.url.partition("://")
            # §48: a Docker-secret-sourced password is arbitrary bytes
            # (base64 output routinely contains `/`, `+`, `=`) — MUST be
            # percent-encoded or it corrupts URL parsing (a literal `/`
            # would be read as a path separator, `@` as a second
            # userinfo delimiter, etc.), which previously caused a
            # silent, confusing `AuthenticationError` rather than a
            # connection actually using the real password.
            return f"{scheme}://:{quote(self.password, safe='')}@{rest}"
        return self.url


@lru_cache
def get_redis_settings() -> RedisSettings:
    return RedisSettings()


def validate_redis_config(environment: str, settings: RedisSettings) -> None:
    """§114/§178/§179: fail closed at startup, in EVERY environment (not
    only production) — a REDIS_ENABLED=true deployment with a missing URL
    or nonsensical pool/timeout/retry value must never start "successfully"
    and fail mysteriously on the first request."""
    if not settings.enabled:
        return
    if not settings.url:
        raise InsecureRedisConfigError(
            "REDIS_ENABLED=true requires REDIS_URL to be set — refusing to start "
            "with an undefined/implicit Redis target."
        )
    if settings.socket_timeout_seconds <= 0:
        raise InsecureRedisConfigError("REDIS_SOCKET_TIMEOUT_SECONDS must be a positive number.")
    if settings.socket_connect_timeout_seconds <= 0:
        raise InsecureRedisConfigError("REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS must be a positive number.")
    if settings.max_connections <= 0:
        raise InsecureRedisConfigError("REDIS_MAX_CONNECTIONS must be a positive integer.")
    if settings.retry_limit < 0:
        raise InsecureRedisConfigError("REDIS_RETRY_LIMIT must be zero or a positive integer.")
    if settings.retry_limit > 5:
        # §52/§100: a generous but bounded ceiling — prevents a
        # misconfigured huge retry count from turning an outage into
        # request amplification across many API nodes at once.
        raise InsecureRedisConfigError("REDIS_RETRY_LIMIT exceeds the sane maximum (5).")
