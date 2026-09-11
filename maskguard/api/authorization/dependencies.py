"""Phase 10.3 §16/§17/§56/§57: `require_permission(...)` — the ONE
abstraction route code uses; no custom role logic spread across route
functions (§16).

Evaluated as early as practical (§56/§57): this dependency runs BEFORE
FastAPI even parses the uploaded file, let alone before any OCR/Core work
— an unauthorized request never reaches `_read_and_validate`/`service.*`,
matching §20's "do not run OCR for a request that is already
unauthorized" and §59's "authorization before acquiring an expensive
processing slot" (the `ConcurrencyLimiter` slot is acquired inside
`service.*`, strictly after this dependency has already run).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Cookie, Depends, Request

from ..audit import event_types as audit_event_types
from ..audit import service as audit_service
from ..audit.models import DECISION_ALLOW, DECISION_DENY, RESULT_DENIED, RESULT_SUCCESS
from ..auth.dependencies import AuthRuntime, get_auth_runtime
from ..auth.errors import AuthenticationRequiredError, SessionExpiredError
from ..auth.models import AuthenticatedIdentity
from ..redisstate.client import RedisUnavailableError
from ..redisstate.errors import DependencyUnavailableError
from .errors import AuthorizationDeniedError
from .permissions import ALL_PERMISSIONS, permissions_for_roles
from .role_config import get_role_mapping

logger = logging.getLogger("maskguard.api.authorization")


def _log_decision(request: Request, identity: AuthenticatedIdentity | None, permission: str, decision: str) -> None:
    # §55: safe fields only — timestamp (implicit, logging module adds
    # it), request_id, issuer, permission, decision. NEVER session id,
    # token, cookie, subject VALUE (only whether one is present — matches
    # the identical discipline `maskguard/api/auth/routes.py` already
    # applies to its own `authentication_succeeded` log line), raw image,
    # OCR text.
    request_id = getattr(request.state, "request_id", None)
    logger.info(
        "authorization_decision request_id=%s issuer=%s subject_present=%s permission=%s decision=%s",
        request_id,
        identity.issuer if identity else None,
        identity is not None,
        permission,
        decision,
    )
    # Phase 10.4 §11/§47: a durable AUTHORIZATION_ALLOWED/DENIED audit
    # event — best-effort (`emit()` never raises, see audit/service.py).
    # `DENY_UNAUTHENTICATED` is intentionally NOT audited here as an
    # authorization event: no identity exists yet, so there is no
    # "authorization decision" to record — Phase 10.2's own
    # `AUTH_LOGIN_*`/session-expiry events cover that case.
    if decision == "ALLOW":
        audit_service.emit(
            audit_event_types.AUTHORIZATION_ALLOWED,
            actor_type="user", actor_id=identity.identity_key if identity else None,
            issuer=identity.issuer if identity else None, request_id=request_id,
            operation=permission, result=RESULT_SUCCESS, decision=DECISION_ALLOW,
        )
    elif decision == "DENY_FORBIDDEN":
        audit_service.emit(
            audit_event_types.AUTHORIZATION_DENIED,
            actor_type="user", actor_id=identity.identity_key if identity else None,
            issuer=identity.issuer if identity else None, request_id=request_id,
            operation=permission, result=RESULT_DENIED, decision=DECISION_DENY,
            reason_code="missing_permission",
        )


def _audit_session_expired(request: Request) -> None:
    # Phase 10.4 §10: a cookie was presented but no live session record
    # matched it (expired/invalidated) — distinct from "no cookie at all"
    # (never audited as a session-expiry event, since no session ever
    # existed to expire).
    audit_service.emit(
        audit_event_types.AUTH_SESSION_EXPIRED,
        actor_type="anonymous", actor_id=None, issuer=None,
        request_id=getattr(request.state, "request_id", None),
        operation="auth.session", result=RESULT_DENIED,
    )


def require_permission(permission: str):
    """§16: `Depends(require_permission("image.analyze"))` is the entire
    integration surface a route needs. §0/§31 backward compatibility:
    when this deployment has not enabled OIDC at all
    (`AuthSettings.oidc_enabled=False`, the default — Phase 10.2's own
    established pattern), authorization is not ACTIVE either — every
    endpoint behaves exactly as it did in every prior phase. A deployment
    that turns OIDC on is explicitly opting into enterprise access
    control for every permission-protected endpoint (see
    docs/authorization-implementation.md's "Opt-in" section for the full
    rationale) — this is a disclosed, documented design decision, not a
    silent scope gap."""
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"require_permission(): unknown permission {permission!r}")  # programmer error, not a runtime path

    def _dependency(
        request: Request,
        session_cookie: str | None = Cookie(default=None, alias="mg_sess"),
        runtime: AuthRuntime = Depends(get_auth_runtime),
    ) -> AuthenticatedIdentity | None:
        if not runtime.settings.oidc_enabled:
            return None

        identity: AuthenticatedIdentity | None = None
        if session_cookie:
            try:
                record = runtime.session_store.get(session_cookie, runtime.settings.session_idle_timeout_seconds)
            except RedisUnavailableError as exc:
                # Phase 10.6 §18/§95/§97: NEVER treat this as
                # "unauthenticated" (fail-open authorization) — an
                # explicit 503, distinct from 401/403.
                raise DependencyUnavailableError("Authorization could not be evaluated; please retry shortly.") from exc
            if record is not None:
                identity = record.identity

        if identity is None:
            _log_decision(request, None, permission, "DENY_UNAUTHENTICATED")
            # §45: an expired/absent session both surface as 401 here —
            # `SessionExpiredError` vs `AuthenticationRequiredError` is
            # already disambiguated by Phase 10.2's own session-cookie
            # presence check; this dependency doesn't need a THIRD
            # distinction, it only needs "is there a valid identity."
            if session_cookie:
                _audit_session_expired(request)
                raise SessionExpiredError()
            raise AuthenticationRequiredError()

        # §49/§96: unmapped identity -> empty role set -> empty permission
        # set -> deterministic DENY. Never fails open.
        roles = get_role_mapping().roles_for(identity.identity_key)
        permissions = permissions_for_roles(roles)
        if permission not in permissions:
            _log_decision(request, identity, permission, "DENY_FORBIDDEN")
            raise AuthorizationDeniedError()

        _log_decision(request, identity, permission, "ALLOW")
        return identity

    return _dependency


@dataclass(frozen=True)
class AuthorizationContext:
    """Used where a single endpoint must check DIFFERENT permissions
    depending on the REQUEST'S OWN CONTENT (§22-24: `/api/v1/review`'s
    mixed accept/reject/manual-detect item list, where the exact
    permission(s) required aren't known until the request body is
    parsed) — `require_permission()` above covers the simpler case where
    one route always needs exactly one fixed permission.

    `enforced=False` means this deployment has not enabled OIDC (§0/§31
    backward compatibility) — every `require(...)` call against this
    context is a guaranteed no-op, exactly matching Phase 9 behavior."""

    enforced: bool
    identity: AuthenticatedIdentity | None
    permissions: frozenset[str]

    def require(self, permission: str) -> None:
        if not self.enforced:
            return
        if permission not in self.permissions:
            raise AuthorizationDeniedError()


def get_authorization_context(
    request: Request,
    session_cookie: str | None = Cookie(default=None, alias="mg_sess"),
    runtime: AuthRuntime = Depends(get_auth_runtime),
) -> AuthorizationContext:
    if not runtime.settings.oidc_enabled:
        return AuthorizationContext(enforced=False, identity=None, permissions=frozenset())

    identity: AuthenticatedIdentity | None = None
    if session_cookie:
        try:
            record = runtime.session_store.get(session_cookie, runtime.settings.session_idle_timeout_seconds)
        except RedisUnavailableError as exc:
            raise DependencyUnavailableError("Authorization could not be evaluated; please retry shortly.") from exc
        if record is not None:
            identity = record.identity

    if identity is None:
        _log_decision(request, None, "review.*", "DENY_UNAUTHENTICATED")
        if session_cookie:
            _audit_session_expired(request)
            raise SessionExpiredError()
        raise AuthenticationRequiredError()

    roles = get_role_mapping().roles_for(identity.identity_key)
    permissions = permissions_for_roles(roles)
    return AuthorizationContext(enforced=True, identity=identity, permissions=permissions)


def resolve_permissions(identity: AuthenticatedIdentity) -> frozenset[str]:
    """Used by `/api/v1/auth/me` (§38) to report the caller's own
    resolved permissions — never a full internal role-configuration
    dump (§37)."""
    roles = get_role_mapping().roles_for(identity.identity_key)
    return permissions_for_roles(roles)
