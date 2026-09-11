"""FastAPI dependency providers (Phase 8.1 §20). `get_service()` is cached
so every request reuses the SAME `MaskGuardService`/`Pipeline`/OCR-engine
instance — constructed once at first use (effectively app startup, since
`app.py` calls it eagerly), not once per request.
"""
from __future__ import annotations

from functools import lru_cache

from .config import ApiSettings, get_settings
from .redisstate.config import get_redis_settings
from .review_token import ReplayStore
from .service import MaskGuardService


def _build_replay_store() -> ReplayStore | None:
    """Phase 10.6 §21: `None` -> `MaskGuardService`/`ReviewTokenIssuer`'s
    own default (`InMemoryReplayStore`) when Redis is disabled — exact
    Phase 8.3/10.3/10.5 behavior, unchanged."""
    if not get_redis_settings().enabled:
        return None
    from .redisstate.client import get_redis_client_and_namespace
    from .review_token import RedisReplayStore

    client, namespace = get_redis_client_and_namespace()
    return RedisReplayStore(client, namespace)


@lru_cache
def get_service() -> MaskGuardService:
    settings = get_settings()
    return MaskGuardService(
        review_token_ttl_seconds=settings.review_token_ttl_seconds,
        max_concurrent_jobs=settings.max_concurrent_jobs,
        review_token_secret=settings.review_token_secret,
        replay_store=_build_replay_store(),
    )


def get_api_settings() -> ApiSettings:
    return get_settings()
