"""Phase 10.5 §2/§16/§56/§63: `require_rate_limit(rate_class)` — the ONE
FastAPI dependency route code uses, mirroring
`authorization/dependencies.py:require_permission`'s own shape so the two
read the same way at a call site.

Ordering (§2/§17/§23, see docs/rate-limit-implementation.md §4 for the
full table): declared as the FIRST dependency parameter on every
protected route, so FastAPI resolves it before `require_permission`/
`get_authorization_context` — rate limiting always runs BEFORE
authorization, and (because it never touches `service.*`/
`run_with_timeout`) always before the `ConcurrencyLimiter` slot is
acquired (§17: "do not consume a concurrency slot before rejecting a
request due to rate limit").

Identity resolution here is INDEPENDENT of (never a replacement for)
`require_permission`'s own — it reuses the same underlying, already-
validated session store lookup (`get_optional_identity`, Phase 10.2) so a
rate-limited request never runs unauthenticated Core work, and an
authenticated caller is rate-limited by their real identity, not a
spoofable header (§6/§10/§45).

Fail-safe policy — TWO DELIBERATELY DIFFERENT policies, selected by
backend (Phase 10.6 §41/§42/§96/§148, read carefully — this is a
disclosed DIVERGENCE from Phase 10.5's own single-instance reasoning):

- **In-memory backend** (`REDIS_ENABLED=false`, single instance,
  UNCHANGED Phase 10.5 behavior): an unexpected internal exception is
  caught and treated as ALLOW (bounded fail-OPEN for this control only)
  — a broken PROCESS-LOCAL limiter degrading its own availability is
  preferable to a self-inflicted denial-of-service, and there is no
  multi-instance bypass surface to exploit in a single-instance topology.
- **Redis backend** (`REDIS_ENABLED=true`, multi-instance): a
  `RedisUnavailableError` raises `DependencyUnavailableError` (503) —
  FAIL CLOSED. §41/§42 are explicit: rate-limit state is now SHARED
  SECURITY STATE (§148's "double-spend" framing) — falling back to
  "allow" (or worse, to per-node local counting) during a Redis outage
  would let an attacker exploit exactly that outage window to bypass the
  shared policy entirely by flooding whichever node currently can't
  reach Redis. No local-memory fallback is implemented for this reason
  (§42's explicit prohibition) — see
  docs/distributed-state-implementation.md §8 for the full rationale.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends, Request, Response

from ..auth.dependencies import get_optional_identity
from ..auth.models import AuthenticatedIdentity
from ..redisstate.client import RedisUnavailableError
from ..redisstate.config import get_redis_settings
from ..redisstate.errors import DependencyUnavailableError
from .config import RateLimitSettings, get_rate_limit_settings
from .errors import RateLimitedError
from .identity import client_ip
from .limiter import RateLimiter

logger = logging.getLogger("maskguard.api.ratelimit")


@lru_cache
def get_rate_limiter() -> RateLimiter:
    settings = get_rate_limit_settings()
    return RateLimiter(max_keys=settings.max_keys, cleanup_interval_seconds=settings.cleanup_interval_seconds)


@lru_cache
def _get_redis_rate_limiter():
    """§33: constructed only when `REDIS_ENABLED=true` — see
    `redis_limiter.py`. Cached per-process like every other Phase 10.x
    singleton (one Lua script registration, one shared connection pool)."""
    from ..redisstate.client import get_redis_client_and_namespace
    from .redis_limiter import RedisRateLimiter

    client, namespace = get_redis_client_and_namespace()
    return RedisRateLimiter(client, namespace)


def _get_backend():
    if get_redis_settings().enabled:
        return _get_redis_rate_limiter(), True  # (backend, is_redis)
    return get_rate_limiter(), False


def _check_one(backend, key: str, capacity: int, window_seconds: int):
    return backend.check(key, capacity, window_seconds)


def require_rate_limit(rate_class: str):
    def _dependency(
        request: Request,
        response: Response,
        settings: RateLimitSettings = Depends(get_rate_limit_settings),
        # §7/§9/§10: the TRUSTED identity only — never a header the
        # client controls. A no-op, safe lookup regardless of whether
        # OIDC is enabled (returns None if so, or if no/invalid cookie).
        identity: AuthenticatedIdentity | None = Depends(get_optional_identity),
    ) -> None:
        if not settings.enabled:
            return  # §0/§56: opt-in, matching every other Phase 10.x control

        backend, is_redis = _get_backend()

        try:
            policy = settings.policy_for(rate_class)
            ip_key = f"ip:{client_ip(request, settings)}"

            decisions = []
            if identity is not None:
                decisions.append((
                    f"identity:{rate_class}:{identity.identity_key}",
                    policy.capacity, policy.window_seconds,
                ))
                if settings.is_layered(rate_class):
                    # §9/§65: a coarser CLIENT-scoped ceiling layered on
                    # top — bounds "many identities from one IP" without
                    # relying on the identity-scoped check alone.
                    decisions.append((
                        f"client:{rate_class}:{ip_key}",
                        policy.capacity * settings.client_multiplier, policy.window_seconds,
                    ))
            else:
                decisions.append((f"anon:{rate_class}:{ip_key}", policy.capacity, policy.window_seconds))

            worst_retry_after = 0
            limit_hit = None
            for key, capacity, window in decisions:
                result = _check_one(backend, key, capacity, window)
                if not result.allowed:
                    worst_retry_after = max(worst_retry_after, result.retry_after_seconds)
                    limit_hit = result
                elif limit_hit is None:
                    # §25: only expose accurate, non-misleading headers —
                    # reflects the narrowest (identity/anon) bucket's own
                    # state, never a value from a check that hasn't run.
                    response.headers["X-RateLimit-Limit"] = str(result.limit)
                    response.headers["X-RateLimit-Remaining"] = str(result.remaining)

            if limit_hit is not None:
                # §51/§52/§53: an operational/security LOG line, never a
                # durable audit row — see docs/rate-limit-implementation.md
                # §14 "Audit integration" for why every 429 is deliberately
                # NOT written to the Phase 10.4 audit store (an attacker
                # generating floods of 429s must not be able to fill the
                # audit database — audit amplification, §52).
                logger.info(
                    "rate_limited request_id=%s rate_class=%s anonymous=%s backend=%s",
                    getattr(request.state, "request_id", None), rate_class, identity is None,
                    "redis" if is_redis else "memory",
                )
                raise RateLimitedError(worst_retry_after)
        except RateLimitedError:
            raise
        except RedisUnavailableError as exc:
            # Phase 10.6 §41/§42/§96: FAIL CLOSED — see module docstring
            # for why this diverges from the in-memory backend's Phase
            # 10.5 fail-open policy. Never falls back to local memory.
            logger.warning("rate_limiter_redis_unavailable rate_class=%s", rate_class)
            raise DependencyUnavailableError("Rate limit could not be evaluated; please retry shortly.") from exc
        except Exception:
            if is_redis:
                # Same fail-closed posture for any OTHER unexpected error
                # once Redis is the backend (§41: "no distributed state ->
                # protected operation fails safely" — not just for the
                # specific RedisUnavailableError case).
                logger.warning("rate_limiter_internal_error rate_class=%s backend=redis", rate_class, exc_info=True)
                raise DependencyUnavailableError("Rate limit could not be evaluated; please retry shortly.") from None
            # In-memory backend: fail OPEN for this control only (Phase
            # 10.5, unchanged — see module docstring).
            logger.warning("rate_limiter_internal_error rate_class=%s backend=memory", rate_class, exc_info=True)
            return

    return _dependency
