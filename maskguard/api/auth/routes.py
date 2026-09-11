"""Phase 10.2 §7/§26-29/§82: `/auth/login`, `/auth/callback`, `/auth/logout`,
`/auth/me`. Registered under `/api/v1/auth` (app.py) — inherits the
existing `/api/v1` security-headers middleware (`Cache-Control: no-store`,
`X-Content-Type-Options`, `X-Frame-Options`) automatically (§62/§81).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import RedirectResponse

from ..audit import event_types as audit_event_types
from ..audit import service as audit_service
from ..audit.models import RESULT_FAILURE, RESULT_SUCCESS
from ..ratelimit.config import AUTH as RL_AUTH
from ..ratelimit.config import READ as RL_READ
from ..ratelimit.dependencies import require_rate_limit
from ..redisstate.client import RedisUnavailableError
from ..redisstate.errors import DependencyUnavailableError
from .config import AuthSettings, get_auth_settings
from .cookies import clear_session_cookie, clear_transaction_cookie, set_session_cookie, set_transaction_cookie
from .csrf import validate_same_origin
from .dependencies import AuthRuntime, get_auth_runtime, get_optional_identity
from .errors import AuthenticationFailedError, OpenRedirectRejectedError
from .models import AuthenticatedIdentity
from .oidc_client import build_authorization_url, exchange_code_for_tokens, generate_nonce, generate_pkce_pair, generate_state, validate_id_token

logger = logging.getLogger("maskguard.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


def _audit_login_failure(request_id: str | None, reason: str) -> None:
    # Phase 10.4 §10/§43: best-effort (emit() never raises). No token/
    # state/nonce/code of any kind — only the safe reason category, same
    # discipline the existing `authentication_failed` log line already
    # follows.
    audit_service.emit(
        audit_event_types.AUTH_LOGIN_FAILURE,
        actor_type="anonymous", actor_id=None, issuer=None, request_id=request_id,
        operation="auth.login", result=RESULT_FAILURE, reason_code=reason,
    )


def _validate_return_path(raw: str | None) -> str:
    """§26: relative-path allowlist only. Rejects anything that could be
    an open redirect: absolute URLs, scheme-relative (`//evil.example`),
    and anything not starting with a single `/`."""
    if not raw or not raw.startswith("/") or raw.startswith("//") or ":" in raw.split("/", 1)[0]:
        return "/"
    return raw


@router.get("/login")
async def login(
    request: Request,
    next: str | None = None,
    runtime: AuthRuntime = Depends(get_auth_runtime),
    settings: AuthSettings = Depends(get_auth_settings),
    # Phase 10.5 §12/§13: pre-authentication — IP-keyed only (no identity
    # exists yet). Bounded, uniform behavior regardless of whether the
    # eventual login would succeed (§13: never reveals user/config/
    # session existence through rate-limit response shape).
    _rate_limited: None = Depends(require_rate_limit(RL_AUTH)),
) -> Response:
    """§7/§8/§9/§10: begins the Authorization Code + PKCE flow. Never the
    implicit flow, never accepts an ID token directly from the browser."""
    if not settings.oidc_enabled:
        raise AuthenticationFailedError()

    return_path = _validate_return_path(next)
    discovery, _ = await runtime.get_discovery()

    state = generate_state()
    nonce = generate_nonce()
    code_verifier, code_challenge = generate_pkce_pair()
    try:
        txn = runtime.transaction_store.create(state=state, nonce=nonce, code_verifier=code_verifier, return_path=return_path)
    except RedisUnavailableError as exc:
        raise DependencyUnavailableError("Login could not be started; please retry shortly.") from exc

    authorization_url = build_authorization_url(discovery, settings, state=state, nonce=nonce, code_challenge=code_challenge)
    response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
    response.headers["Cache-Control"] = "no-store"  # §81
    set_transaction_cookie(response, settings, txn.transaction_id)
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    runtime: AuthRuntime = Depends(get_auth_runtime),
    settings: AuthSettings = Depends(get_auth_settings),
    txn_cookie: str | None = Cookie(default=None, alias="mg_txn"),
    # Phase 10.5 §14: IP-keyed only — deliberately NEVER keyed on
    # `state`/`code`/`error` (untrusted request content, §14's own
    # explicit warning). State/nonce/PKCE validation below is completely
    # unaffected either way (Phase 10.2, unchanged).
    _rate_limited: None = Depends(require_rate_limit(RL_AUTH)),
) -> Response:
    """§27: every one of the 10 listed callback steps. ANY failure raises
    `AuthenticationFailedError` — never a partially-created session
    (§27: "do not partially create a session")."""
    request_id = getattr(request.state, "request_id", None)

    if error or not code or not state:
        logger.info("event=authentication_failed reason=missing_or_provider_error request_id=%s", request_id)
        _audit_login_failure(request_id, "missing_or_provider_error")
        raise AuthenticationFailedError()

    # §27 step 1 / §79: one-time consume — a replayed callback (same
    # transaction cookie reused, or the store already evicted it) finds
    # nothing and fails closed.
    if not txn_cookie:
        logger.info("event=authentication_failed reason=missing_transaction_cookie request_id=%s", request_id)
        _audit_login_failure(request_id, "missing_transaction_cookie")
        raise AuthenticationFailedError()
    try:
        txn = runtime.transaction_store.consume(txn_cookie, settings.transaction_ttl_seconds)
    except RedisUnavailableError as exc:
        raise DependencyUnavailableError("Login could not be completed; please retry shortly.") from exc
    if txn is None:
        logger.info("event=authentication_failed reason=invalid_or_expired_transaction request_id=%s", request_id)
        _audit_login_failure(request_id, "invalid_or_expired_transaction")
        raise AuthenticationFailedError()

    # §8/§27 step 1: state must match exactly what THIS transaction issued.
    if not _constant_time_eq(txn.state, state):
        logger.info("event=authentication_failed reason=state_mismatch request_id=%s", request_id)
        _audit_login_failure(request_id, "state_mismatch")
        raise AuthenticationFailedError()

    discovery, key_provider = await runtime.get_discovery()

    # §27 steps 2-3: exchange server-side.
    try:
        token_response = await exchange_code_for_tokens(
            discovery, settings, code=code, code_verifier=txn.code_verifier, http_client=runtime.http_client
        )
    except Exception:
        logger.info("event=authentication_failed reason=token_exchange_failed request_id=%s", request_id)
        _audit_login_failure(request_id, "token_exchange_failed")
        raise AuthenticationFailedError() from None

    id_token = token_response.get("id_token")
    if not id_token:
        logger.info("event=authentication_failed reason=missing_id_token request_id=%s", request_id)
        _audit_login_failure(request_id, "missing_id_token")
        raise AuthenticationFailedError()

    # §27 steps 4-8: full cryptographic + semantic validation (issuer,
    # audience, signature, expiry, nonce — see oidc_client.py).
    try:
        claims = await validate_id_token(
            id_token, discovery=discovery, settings=settings, key_provider=key_provider, expected_nonce=txn.nonce
        )
    except AuthenticationFailedError:
        logger.info("event=authentication_failed reason=id_token_validation_failed request_id=%s", request_id)
        _audit_login_failure(request_id, "id_token_validation_failed")
        raise

    # §27 step 9: create a BRAND NEW session (never reuses txn.transaction_id
    # or any pre-existing identifier — fixation protection, §21/§49/§50).
    identity = AuthenticatedIdentity(
        subject=claims.subject,
        issuer=claims.issuer,
        authenticated_at=_now(),
        provider="oidc",
        email=claims.email,
        display_name=claims.display_name,
    )
    try:
        record = runtime.session_store.create(identity, settings.session_idle_timeout_seconds, settings.session_absolute_timeout_seconds)
    except RedisUnavailableError as exc:
        raise DependencyUnavailableError("Login could not be completed; please retry shortly.") from exc
    logger.info(
        "event=authentication_succeeded request_id=%s issuer=%s subject_present=true",
        request_id,
        claims.issuer,
    )
    audit_service.emit(
        audit_event_types.AUTH_LOGIN_SUCCESS,
        actor_type="user", actor_id=identity.identity_key, issuer=identity.issuer, request_id=request_id,
        operation="auth.login", result=RESULT_SUCCESS,
    )

    response = RedirectResponse(url=txn.return_path, status_code=status.HTTP_302_FOUND)
    response.headers["Cache-Control"] = "no-store"  # §81
    set_session_cookie(response, settings, record.session_id)
    clear_transaction_cookie(response, settings)  # §27 step 10: one-time transaction state cleared
    return response


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    runtime: AuthRuntime = Depends(get_auth_runtime),
    settings: AuthSettings = Depends(get_auth_settings),
    session_cookie: str | None = Cookie(default=None, alias="mg_sess"),
    # Phase 10.5 §15: rate limiting is independent of, and runs BEFORE,
    # the Origin/CSRF check below — neither interferes with the other
    # (§15 explicitly requires SameSite+Origin validation stay unchanged).
    _rate_limited: None = Depends(require_rate_limit(RL_AUTH)),
) -> dict:
    """§28/§29: POST-only (not a plain GET a `<img>` tag could trigger),
    Origin-validated (§25/§29 — logout CSRF)."""
    if settings.oidc_enabled:
        expected_origins = tuple(o for o in (settings.redirect_uri,) if o)
        # Same-origin as the configured redirect URI's own origin — the
        # narrowest correct allowlist available without introducing a
        # separate "frontend origin" config value (§25/§63: preserve
        # current CORS/same-origin policy, don't invent a new one).
        from urllib.parse import urlparse

        origins = tuple(f"{urlparse(u).scheme}://{urlparse(u).netloc}" for u in expected_origins) or ("null",)
        validate_same_origin(request, expected_origins=origins)

    if session_cookie:
        # Look up WHO before deleting, so the audit event can name the
        # actor — the record is about to be invalidated either way.
        # Best-effort only: a lookup failure must not block the
        # AUTHORITATIVE deletion below (§149) — it only means the audit
        # event is skipped, never that logout itself fails.
        try:
            record = runtime.session_store.get(session_cookie, runtime.settings.session_idle_timeout_seconds)
        except RedisUnavailableError:
            record = None
        try:
            runtime.session_store.delete(session_cookie)  # §28/§149: server-side invalidation, not just cookie deletion
        except RedisUnavailableError as exc:
            # §149 is mandatory: logout MUST propagate through shared
            # state. If we cannot even attempt the deletion, we must NOT
            # claim success (clearing only the browser cookie while the
            # server-side session survives would be a silent logout
            # failure — worse than an honest error).
            raise DependencyUnavailableError("Logout could not be completed; please retry shortly.") from exc
        if record is not None:
            audit_service.emit(
                audit_event_types.AUTH_LOGOUT,
                actor_type="user", actor_id=record.identity.identity_key, issuer=record.identity.issuer,
                request_id=getattr(request.state, "request_id", None), operation="auth.logout", result=RESULT_SUCCESS,
            )
    clear_session_cookie(response, settings)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "logged_out"}


@router.get("/me")
async def me(
    identity: AuthenticatedIdentity | None = Depends(get_optional_identity),
    # Phase 10.5 §16: bounds excessive polling without breaking normal
    # browser startup (READ class — generous default, see config.py).
    _rate_limited: None = Depends(require_rate_limit(RL_READ)),
) -> dict:
    """§82(Phase10.2)/§38(Phase10.3): safe identity metadata only — never
    a token, never a session id (§80). Phase 10.3 §38 adds the caller's
    own RESOLVED PERMISSIONS (never the full internal role-configuration,
    §37) so the frontend can drive UX (§39/§40) without needing its own
    copy of the role->permission logic — the backend remains the sole
    authority; this is a convenience projection of what the backend would
    already enforce, not a second source of truth."""
    if identity is None:
        return {"authenticated": False}

    from ..authorization.dependencies import resolve_permissions  # local import: auth/ stays import-independent of authorization/ except at this one read-only call site

    return {
        "authenticated": True,
        "subject": identity.subject,
        "issuer": identity.issuer,
        "display_name": identity.display_name,
        "email": identity.email,
        "permissions": sorted(resolve_permissions(identity)),
    }


def _constant_time_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _now() -> float:
    import time

    return time.time()
