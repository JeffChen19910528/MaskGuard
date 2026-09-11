"""GET /api/v1/health (Phase 8.1 §6). Never runs OCR or touches an image —
this is a liveness/readiness check only. Never leaks filesystem paths, API
keys, or environment configuration.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from ... import __version__ as app_version
from .. import __api_version__
from ..dependencies import get_service
from ..redisstate.config import get_redis_settings
from ..schemas import HealthResponse
from ..service import MaskGuardService

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(service: MaskGuardService = Depends(get_service)) -> HealthResponse:
    """§54: LIVENESS only — "is this process alive." Never checks Redis
    (or anything else external) — a temporary Redis outage must not make
    a perfectly healthy process get killed/restarted by an orchestrator's
    liveness probe (that would only make the outage worse, not better).
    Docker's own `healthcheck:` in docker-compose*.yml targets this."""
    return HealthResponse(
        status="ok",
        api_version=__api_version__,
        app_version=app_version,
        ocr_engine_available=service.ocr_engine_available,
    )


@router.get("/ready")
def ready(response: Response) -> dict:
    """§53/§54/§55/§56: READINESS — "are the dependencies required for
    SECURE operation available." When `REDIS_ENABLED=false` (default,
    single-instance), Redis is not a dependency at all and this always
    reports ready. When `REDIS_ENABLED=true`, a Redis outage makes this
    endpoint report `not_ready` — never `ready` — so a load balancer /
    orchestrator can correctly stop routing traffic to a node that cannot
    safely evaluate session/replay/rate-limit state, WITHOUT killing the
    process itself (that remains liveness's job, above).

    §55/§56: never returns a password, connection string, internal
    state, or raw exception — only a safe status and, when not ready, a
    generic reason classification."""
    redis_settings = get_redis_settings()
    if not redis_settings.enabled:
        return {"status": "ready", "redis": "not_required"}

    from ..redisstate.client import get_redis_client, ping

    client = get_redis_client(redis_settings)
    if ping(client):
        return {"status": "ready", "redis": "available"}

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "not_ready", "redis": "unavailable"}
