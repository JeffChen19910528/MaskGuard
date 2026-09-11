"""Phase 10.4 §2/§43/§44/§98: the ONLY entry point every other module
calls to record an audit event (`emit()`), and the query/integrity
wrappers the `/api/v1/audit` route and internal tooling use.

**Audit failure policy (§2/§43/§44, decided explicitly)**: `emit()` is
ALWAYS best-effort. A validation failure or storage outage is caught,
logged as a safe `AUDIT_STORE_UNAVAILABLE`/`AUDIT_EVENT_REJECTED`
application-log line (§98 — never the raw event payload, never a
secret), and otherwise ignored — it NEVER raises into the caller. This is
Option B from §2's own menu ("continue with security-safe operation"),
chosen because MaskGuard's actual security decisions
(authentication/authorization/PolicyEngine/redaction/verification) are
made by other modules entirely and have ALREADY completed by the time
`emit()` is called at each call site (see `routes/images.py`,
`routes/review.py`, `auth/routes.py`, `authorization/dependencies.py`) —
audit observes a decision after the fact, so failing the audit write can
only ever mean "this security event goes unrecorded," never "this
security event's OUTCOME changes." Making audit block or fail the
request (Option A) would let an audit-storage outage become a
denial-of-service against MaskGuard's actual purpose (processing
sensitive images safely) for no security benefit — the fail-safe
direction here is to keep processing image requests and note the audit
gap, not to stop protecting users' documents because a bookkeeping
database is unavailable.
"""
from __future__ import annotations

import logging
import secrets
from functools import lru_cache

from .config import AuditSettings, get_audit_settings
from .models import AuditEvent
from .sanitizer import AuditValidationError, build_event
from .storage import AuditStorageUnavailableError, AuditStore

logger = logging.getLogger("maskguard.api.audit")


@lru_cache
def get_audit_store() -> AuditStore | None:
    settings = get_audit_settings()
    if not settings.audit_enabled:
        return None
    # §32: production requires an explicit key (validate_production_audit_config,
    # called at app startup); development auto-generates a process-local one —
    # same documented "chain verifiable only within this process's lifetime"
    # caveat as Phase 8.3's review-token secret.
    key = settings.integrity_key.encode("utf-8") if settings.integrity_key else secrets.token_bytes(32)
    try:
        return AuditStore(settings.db_path, key)
    except Exception:
        # §2/§43/§44: ANY init failure (not just the SQLite-specific
        # `AuditStorageUnavailableError` — also e.g. a permission error
        # creating the storage directory, a full disk, an invalid path)
        # must never propagate. Never `except AuditStorageUnavailableError`
        # alone here — this is the one place a broad `except Exception` is
        # deliberate and correct, since audit initialization failing must
        # be strictly less disruptive than the image-processing request
        # that triggered it.
        logger.warning("event=AUDIT_STORE_UNAVAILABLE reason=init_failed")
        return None


def emit(
    event_type: str,
    *,
    actor_type: str,
    actor_id: str | None,
    issuer: str | None,
    request_id: str | None,
    operation: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    result: str,
    decision: str | None = None,
    reason_code: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort, never raises — see module docstring."""
    settings = get_audit_settings()
    if not settings.audit_enabled:
        return
    store = get_audit_store()
    if store is None:
        return
    try:
        event = build_event(
            settings,
            event_type=event_type, actor_type=actor_type, actor_id=actor_id, issuer=issuer,
            request_id=request_id, operation=operation, resource_type=resource_type,
            resource_id=resource_id, result=result, decision=decision, reason_code=reason_code,
            metadata=metadata,
        )
        store.append(event)
    except AuditValidationError as exc:
        logger.warning("event=AUDIT_EVENT_REJECTED event_type=%s reason=%s", event_type, exc)
    except AuditStorageUnavailableError:
        logger.warning("event=AUDIT_STORE_UNAVAILABLE event_type=%s", event_type)


def query(settings: AuditSettings, **kwargs) -> list[AuditEvent]:
    store = get_audit_store()
    if store is None:
        return []
    try:
        return store.query(**kwargs)
    except AuditStorageUnavailableError:
        logger.warning("event=AUDIT_STORE_UNAVAILABLE operation=query")
        return []


def verify_integrity() -> tuple[bool, str | None]:
    """§84: internal verification operation — exposed publicly only
    behind `audit.read` (see `routes.py`), never anonymously."""
    store = get_audit_store()
    if store is None:
        return True, None  # nothing to verify — not a failure
    try:
        return store.verify_integrity()
    except AuditStorageUnavailableError:
        return False, None
