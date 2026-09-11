"""Phase 10.4 §36/§38/§39/§40/§41/§42/§84: `GET /api/v1/audit` (bounded,
filtered query) and `GET /api/v1/audit/integrity` (chain verification) —
both gated by `audit.read` (Phase 10.3). Registered only when
`AUDIT_ENABLED=true` (§0, same opt-in pattern as `auth`/`authorization`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request

from ..auth.models import AuthenticatedIdentity
from ..authorization.dependencies import require_permission
from ..authorization.permissions import AUDIT_READ
from ..errors import ApiError
from ..ratelimit.config import AUDIT_QUERY as RL_AUDIT_QUERY
from ..ratelimit.dependencies import require_rate_limit
from . import event_types, service
from .config import AuditSettings, get_audit_settings
from .models import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])


def _event_to_dict(event: AuditEvent) -> dict:
    """§40: typed serialization — the SAME schema every event was
    validated against on write, never a raw DB row dump."""
    return {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "schema_version": event.schema_version,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "issuer": event.issuer,
        "request_id": event.request_id,
        "operation": event.operation,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "result": event.result,
        "decision": event.decision,
        "reason_code": event.reason_code,
        "metadata": event.metadata,
        "hash": event.hash,
        "prev_hash": event.prev_hash,
    }


@router.get("")
async def list_audit_events(
    request: Request,
    event_type: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    operation: str | None = Query(default=None),
    result: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    since: str | None = Query(default=None, description="ISO 8601 UTC, inclusive"),
    until: str | None = Query(default=None, description="ISO 8601 UTC, inclusive"),
    limit: int = Query(default=50, ge=1),
    offset: int = Query(default=0, ge=0),
    settings: AuditSettings = Depends(get_audit_settings),
    # Phase 10.5 §22/§48/§96: audit.read remains authoritative for
    # WHO may query at all — rate limiting complements it, never
    # replaces the existing page-size/time-range bounds below.
    _rate_limited: None = Depends(require_rate_limit(RL_AUDIT_QUERY)),
    identity: AuthenticatedIdentity | None = Depends(require_permission(AUDIT_READ)),
) -> dict:
    # §39: bounded page size and time range — never an unbounded scan.
    bounded_limit = min(limit, settings.max_query_page_size)
    if since is None:
        earliest_allowed = datetime.now(timezone.utc) - timedelta(days=settings.max_query_range_days)
        since = earliest_allowed.isoformat()
    else:
        try:
            requested_since = datetime.fromisoformat(since)
        except ValueError:
            raise ApiError("`since` must be ISO 8601.", code="VALIDATION_ERROR", status_code=422) from None
        earliest_allowed = datetime.now(timezone.utc) - timedelta(days=settings.max_query_range_days)
        if requested_since.tzinfo is None:
            requested_since = requested_since.replace(tzinfo=timezone.utc)
        if requested_since < earliest_allowed:
            since = earliest_allowed.isoformat()

    events = service.query(
        settings,
        event_type=event_type, actor_id=actor_id, operation=operation, result=result,
        request_id=request_id, since=since, until=until, limit=bounded_limit, offset=offset,
    )

    # §42: audit-of-audit-access — the query itself is logged as an event,
    # but NEVER the raw query string/full filter set beyond safe,
    # already-bounded fields (§42: "sanitize it" if it could contain
    # sensitive search parameters — `event_type`/`operation`/`result` are
    # closed-vocabulary safe values; `actor_id`/`request_id` are already
    # length-bounded correlation identifiers, not free text).
    identity_key = identity.identity_key if identity is not None else None
    service.emit(
        event_types.AUDIT_ACCESS,
        actor_type="user" if identity is not None else "anonymous",
        actor_id=identity_key,
        issuer=identity.issuer if identity is not None else None,
        request_id=getattr(request.state, "request_id", None),
        operation="audit.read",
        resource_type="audit_query",
        resource_id=None,
        result="SUCCESS",
        metadata={"result_count": len(events)},
    )

    return {"events": [_event_to_dict(e) for e in events], "count": len(events)}


@router.get("/integrity")
async def audit_integrity(
    # Phase 10.5 §49: integrity verification walks the WHOLE chain — the
    # most expensive audit operation, so it gets its OWN rate-limit check
    # (same AUDIT_QUERY class/budget as the query endpoint — sharing one
    # class is a deliberate "do not over-engineer" simplification, §49).
    _rate_limited: None = Depends(require_rate_limit(RL_AUDIT_QUERY)),
    identity: AuthenticatedIdentity | None = Depends(require_permission(AUDIT_READ)),
) -> dict:
    """§84: PASS/FAIL only — never publicly exposed (gated identically to
    the query endpoint)."""
    ok, first_bad_event_id = service.verify_integrity()
    return {"integrity": "PASS" if ok else "FAIL", "first_invalid_event_id": first_bad_event_id}
