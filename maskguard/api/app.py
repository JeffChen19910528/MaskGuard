"""FastAPI application factory (Phase 8.1 §4). Application initialization
lives here — NOT folded into `cli.py` (§31: CLI and API are two independent
entry points over the same Core, neither depends on the other).

Start locally:
    python -m uvicorn maskguard.api.app:app --host 127.0.0.1 --port 8000
or:
    python -m maskguard.api
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__ as app_version
from . import __api_version__
from .audit.config import get_audit_settings, validate_production_audit_config
from .audit.routes import router as audit_router
from .auth.config import get_auth_settings, validate_production_auth_config
from .auth.routes import router as auth_router
from .config import get_settings, validate_production_secret
from .dependencies import get_service
from .deployment_profile import get_deployment_profile, validate_deployment_profile
from .errors import register_exception_handlers
from .middleware import MaxRequestBodySizeMiddleware
from .ratelimit.config import get_rate_limit_settings, validate_production_rate_limit_config
from .redisstate.config import InsecureRedisConfigError, get_redis_settings, validate_redis_config
from .routes import health_router, images_router, review_router

logger = logging.getLogger("maskguard.api")

#: A client-supplied X-Request-ID must be a short, plain opaque token — not
#: arbitrary header content — or it is replaced with a generated one (§16).
_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Construct (not run) the shared Core service now, at process startup,
    # rather than lazily on the first request (§20) — the first caller
    # shouldn't pay OCR-engine construction latency.
    get_service()
    logger.info("maskguard_api_started app_version=%s api_version=%s", app_version, __api_version__)
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    # Phase 9 §17: fail CLOSED before the process ever binds a port or
    # accepts a connection — not lazily on first request, not silently
    # falling back to an auto-generated secret in production. This runs at
    # import time (`app = create_app()` below), so a misconfigured
    # production container exits immediately with a clear error instead of
    # starting up "successfully" with a weak/absent secret.
    validate_production_secret(settings.environment, settings.review_token_secret)

    # Phase 10.2 §39/§41: same fail-closed discipline, extended to OIDC
    # configuration — validated at import time, never lazily on first
    # login attempt. A no-op when OIDC_ENABLED is unset/false (§0/§31: this
    # phase must not make authentication mandatory by accident).
    auth_settings = get_auth_settings()
    validate_production_auth_config(settings.environment, auth_settings)

    # Phase 10.4 §43/§79: same fail-closed discipline, extended to audit
    # configuration. No-op when AUDIT_ENABLED is unset/false.
    audit_settings = get_audit_settings()
    validate_production_audit_config(settings.environment, audit_settings)

    # Phase 10.5 §55/§60/§79: same fail-closed discipline, extended to
    # rate-limit configuration — validated (bounds/positivity) in EVERY
    # environment, not only when RATE_LIMIT_ENABLED. No-op behaviorally
    # when RATE_LIMIT_ENABLED is unset/false (§0/§56).
    rate_limit_settings = get_rate_limit_settings()
    validate_production_rate_limit_config(settings.environment, rate_limit_settings)

    # Phase 10.6 §114/§178: same fail-closed discipline, extended to
    # Redis configuration — validated in EVERY environment, not only
    # when REDIS_ENABLED. No-op when unset/false (§0).
    redis_settings = get_redis_settings()
    validate_redis_config(settings.environment, redis_settings)

    # Phase 10.6: REDIS_ENABLED=true signals multi-instance intent (§113
    # — there is no separate MULTI_INSTANCE flag, see redisstate/config.py).
    # A review-token secret that auto-generates PER PROCESS would make
    # Node A's issued tokens permanently unverifiable on Node B — not a
    # code bug, but a silent, confusing cross-node failure a startup
    # check can catch instead (§114's "avoid dangerous partial
    # configuration... fail startup safely" applied to this specific
    # cross-cutting interaction between Redis and the EXISTING Phase 9
    # review-token-secret config).
    if redis_settings.enabled and not settings.review_token_secret:
        raise InsecureRedisConfigError(
            "REDIS_ENABLED=true requires an explicit MASKGUARD_REVIEW_TOKEN_SECRET(_FILE) — "
            "an auto-generated per-process secret would make review tokens issued by one "
            "instance unverifiable by another, silently breaking cross-node review."
        )

    # Phase 10.7 §3/§4/§5/§6/§32: the declared deployment profile's
    # required security controls — checked LAST, after every individual
    # control's own config is already known to be internally valid, so
    # this is purely "are the RIGHT controls turned on together," never
    # duplicating the checks above. A no-op for the default
    # `development` profile (§0) — existing deployments that have never
    # set MASKGUARD_DEPLOYMENT_PROFILE see zero behavior change.
    deployment_profile = get_deployment_profile()
    validate_deployment_profile(
        deployment_profile,
        oidc_enabled=auth_settings.oidc_enabled,
        authz_configured=bool(os.environ.get("AUTHZ_ROLE_MAPPING_FILE")),
        audit_enabled=audit_settings.audit_enabled,
        rate_limit_enabled=rate_limit_settings.enabled,
        redis_enabled=redis_settings.enabled,
    )

    app = FastAPI(
        title="MaskGuard API",
        version=__api_version__,
        description=(
            "Image sensitive-data detection and redaction API. Wraps the MaskGuard "
            "Core pipeline (OCR -> Detection -> Risk -> Policy -> Redaction -> "
            "Verification -> Whole-Image Sanity Scan) over HTTP. Stateless: no "
            "persistent storage, no accounts (see Phase 8.1 report — persistence "
            "is a later phase's scope)."
        ),
        lifespan=_lifespan,
        # Phase 10.7 §29: interactive API documentation (Swagger UI,
        # ReDoc, and the raw OpenAPI schema) is disabled in production —
        # an enterprise deployment should not publicly expose its full
        # endpoint/schema surface by default. Development/test keep it
        # (useful for local iteration); verified via direct HTTP request
        # (`tests/test_deployment_profile.py`-adjacent API test) that all
        # three paths 404 in production.
        docs_url=None if settings.environment == "production" else "/docs",
        redoc_url=None if settings.environment == "production" else "/redoc",
        openapi_url=None if settings.environment == "production" else "/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),  # empty by default (§19) — never "*"
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        # Response headers a cross-origin browser fetch() may actually READ
        # (distinct from `allow_headers`, which is about REQUEST headers).
        # Without this, `X-Request-ID` (Phase 8.1 §16) and the Phase 8.3
        # `X-Review-*` headers are sent but invisible to frontend JS.
        expose_headers=[
            "X-Request-ID",
            "X-Review-Status", "X-Review-Needs-Human-Review", "X-Review-Blocked", "X-Review-Detection-Count",
        ],
    )

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next):
        incoming = request.headers.get("x-request-id")
        request_id = incoming if incoming and _SAFE_REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def _security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        # Applied to the actual API surface only — never to /docs,
        # /openapi.json, /redoc (§29/§38: don't break the dev-mode Swagger
        # UI, which loads its own CDN-hosted JS/CSS and needs normal
        # response headers to do so).
        if request.url.path.startswith("/api/v1"):
            # Never let a browser guess/sniff a different content type for
            # a response than what we declared.
            response.headers["X-Content-Type-Options"] = "nosniff"
            # §30: every /api/v1 response — JSON findings AND the redacted
            # image bytes from /redact and /review — can carry
            # business-sensitive content. None of it is a static asset;
            # none of it should ever be cached by a browser, proxy, or CDN.
            response.headers["Cache-Control"] = "no-store"
            # This API is never meant to be framed/embedded by another site.
            response.headers["X-Frame-Options"] = "DENY"
        return response

    register_exception_handlers(app)

    app.include_router(health_router, prefix="/api/v1", tags=["health"])
    app.include_router(images_router, prefix="/api/v1", tags=["images"])
    app.include_router(review_router, prefix="/api/v1", tags=["review"])
    # Phase 10.2 §0/§31: registered ONLY when OIDC_ENABLED — a deployment
    # that hasn't configured enterprise identity gets no new attack
    # surface at all, and analyze/redact/verify/review's existing
    # public/private semantics are completely unchanged either way (no
    # endpoint in this phase was made to require authentication — that is
    # Phase 10.3's decision to make, not this phase's).
    if auth_settings.oidc_enabled:
        app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
    # Phase 10.4 §0: registered ONLY when AUDIT_ENABLED — no new attack
    # surface for a deployment that hasn't opted in.
    if audit_settings.audit_enabled:
        app.include_router(audit_router, prefix="/api/v1", tags=["audit"])

    # Registered LAST so it becomes the OUTERMOST ASGI layer (Starlette
    # wraps middleware in reverse registration order) — it must see raw
    # request bytes before CORS/request-id/routing/multipart-parsing ever
    # touch them (Phase 8.4 §5/§11 — see middleware.py).
    app.add_middleware(MaxRequestBodySizeMiddleware, max_bytes=settings.max_request_body_bytes)

    return app


app = create_app()
