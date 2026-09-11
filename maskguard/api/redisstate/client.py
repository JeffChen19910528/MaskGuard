"""Phase 10.6 §50/§51/§52/§98: a single bounded, pooled Redis client per
process, and the ONE place raw `redis` exceptions get translated into
`RedisUnavailableError` — callers (session/review/ratelimit backends)
never see a raw `redis.exceptions.*` (which can carry connection-string
detail) escape past this module.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import redis
from redis.backoff import ConstantBackoff
from redis.retry import Retry

from .config import RedisSettings, get_redis_settings

logger = logging.getLogger("maskguard.api.redisstate")


class RedisUnavailableError(RuntimeError):
    """§98: constructed with a SAFE, generic message only — the original
    `redis` exception (which may include host/port) is logged server-side
    (`logger.warning`, at the raise site) but never attached to this
    exception's own message, so nothing upstream can accidentally surface
    it to a client response."""


@lru_cache
def get_redis_client(settings: RedisSettings | None = None) -> redis.Redis:
    """§50: one bounded connection pool per process — never unlimited,
    never one connection per request."""
    s = settings or get_redis_settings()
    pool = redis.ConnectionPool.from_url(
        s.connection_url(),
        max_connections=s.max_connections,
        socket_timeout=s.socket_timeout_seconds,
        socket_connect_timeout=s.socket_connect_timeout_seconds,
        # §52/§100: bounded retry ONLY on the transport-level connection
        # attempt itself (never an unbounded loop) — application-level
        # commands still raise on failure rather than silently retrying
        # past `retry_limit`, so a request fails fast and predictably.
        retry=Retry(ConstantBackoff(0), s.retry_limit),
        retry_on_timeout=s.retry_limit > 0,
        health_check_interval=30,
        # Decoded at the CONNECTION level (not the `Redis()` constructor
        # — that argument is ignored once an existing `connection_pool`
        # is supplied) so every caller gets plain `str`, never `bytes`.
        decode_responses=True,
    )
    return redis.Redis(connection_pool=pool)


def get_redis_namespace(settings: RedisSettings | None = None) -> str:
    """Resolves `RedisSettings.resolved_namespace()` against the current
    deployment environment (`ApiSettings.environment`) — the ONE place
    that combines `redisstate` config with the top-level api config, so
    every consumer (session store, replay store, rate limiter) stops
    re-deriving this itself (previously duplicated across
    `dependencies.py`, `auth/dependencies.py`, `ratelimit/dependencies.py`)."""
    from ..config import get_settings

    s = settings or get_redis_settings()
    return s.resolved_namespace(get_settings().environment)


def get_redis_client_and_namespace(settings: RedisSettings | None = None) -> tuple[redis.Redis, str]:
    """Convenience for the common case (a Redis-backed store needs both)
    — equivalent to calling `get_redis_client()`/`get_redis_namespace()`
    separately, just without every call site repeating the pairing."""
    s = settings or get_redis_settings()
    return get_redis_client(s), get_redis_namespace(s)


def ping(client: redis.Redis) -> bool:
    """§56: used by the readiness endpoint — returns a plain bool, never
    raises, never leaks exception detail."""
    try:
        return bool(client.ping())
    except redis.RedisError:
        return False


def safe_call(operation_name: str, func, *args, **kwargs):
    """§98/§52: the ONE call-site wrapper every backend uses — converts
    any `redis.RedisError` into `RedisUnavailableError` with a generic
    message, logging the real exception (never host/password) server-side
    only."""
    try:
        return func(*args, **kwargs)
    except redis.RedisError as exc:
        logger.warning("redis_operation_failed operation=%s error_type=%s", operation_name, type(exc).__name__)
        raise RedisUnavailableError(f"Redis operation '{operation_name}' failed.") from exc
