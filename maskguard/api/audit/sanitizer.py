"""Phase 10.4 §5/§20/§21/§22/§49/§70/§72/§86: the ONE place raw
application data becomes a validated `AuditEvent`. Every audit-writing
call site in this codebase goes through `build_event()` — no caller
constructs an `AuditEvent` directly (§21: "single audit sanitization
boundary").

This is defense in depth, not the only safeguard (§5: "must be enforced
by code and tests," not developer discipline alone) — call sites are
ALSO written to only ever pass safe, pre-selected fields (never a raw
request/response body, §79/§80), but this module still independently
rejects anything that slips through: forbidden-looking metadata keys,
oversized fields, wrong types, control characters, and unknown event
types.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone

from .config import AuditSettings
from .event_types import ALL_EVENT_TYPES, RESERVED_FOR_FUTURE_USE
from .models import (
    MAX_ACTOR_ID_LENGTH, MAX_ISSUER_LENGTH, MAX_OPERATION_LENGTH, MAX_REASON_CODE_LENGTH,
    MAX_REQUEST_ID_LENGTH, MAX_RESOURCE_ID_LENGTH, MAX_RESOURCE_TYPE_LENGTH,
    SCHEMA_VERSION, VALID_ACTOR_TYPES, VALID_DECISIONS, VALID_RESULTS,
    AuditEvent, _ALLOWED_METADATA_VALUE_TYPES,
)

#: §20: metadata KEY names that must never appear — a safety net, since
#: call sites should never pass these to begin with (§5/§78: "must NEVER
#: record: review token, HMAC, token payload, nonce, session ID").
#: Substring match, case-insensitive, so `access_token`/`refresh_token`/
#: `client_secret`/`db_password`/`session_cookie` etc. are all caught by
#: their common root, not just an exact name.
_FORBIDDEN_KEY_SUBSTRINGS = (
    "token", "secret", "password", "passwd", "cookie", "authorization",
    "bearer", "private_key", "privatekey", "ssh_key", "sshkey", "api_key",
    "apikey", "nonce", "pkce", "verifier", "credential", "jwt",
)

#: §49/§72: ALL C0 control characters (including newline/CR/tab) plus DEL
#: are stripped from every string field — closes newline/log injection and
#: terminal-escape injection at the sanitization boundary itself, never
#: left to whatever eventually renders/logs the event. A plain space
#: (0x20) is the only "whitespace-adjacent" character preserved.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


class AuditValidationError(ValueError):
    """Raised by `build_event()` for anything malformed/forbidden —
    callers MUST treat this as "do not write this event" (see
    `service.py`), never as a reason to raise into the caller's own
    request (§2/§43/§44: audit failure must never weaken security)."""


def _clean_string(value: str, max_length: int, field_name: str) -> str:
    if not isinstance(value, str):
        raise AuditValidationError(f"{field_name} must be a string.")
    # §72: normalize + strip control characters BEFORE the length check,
    # so a padding-with-control-chars trick can't bypass the length bound.
    cleaned = _CONTROL_CHAR_RE.sub("", unicodedata.normalize("NFC", value))
    if len(cleaned) > max_length:
        raise AuditValidationError(f"{field_name} exceeds the {max_length}-character limit.")
    return cleaned


def _clean_optional_string(value: str | None, max_length: int, field_name: str) -> str | None:
    if value is None:
        return None
    return _clean_string(value, max_length, field_name)


def _validate_metadata(metadata: dict, settings: AuditSettings) -> dict:
    if not isinstance(metadata, dict):
        raise AuditValidationError("metadata must be a dict.")
    if len(metadata) > settings.max_metadata_keys:
        raise AuditValidationError(f"metadata has too many keys (max {settings.max_metadata_keys}).")

    cleaned: dict[str, str | int | float | bool | None] = {}
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise AuditValidationError("metadata keys must be strings.")
        key_clean = _clean_string(key, settings.max_metadata_key_length, "metadata key")
        lowered = key_clean.lower()
        if any(bad in lowered for bad in _FORBIDDEN_KEY_SUBSTRINGS):
            raise AuditValidationError(f"metadata key {key_clean!r} looks like a forbidden secret/token field.")

        if not isinstance(value, _ALLOWED_METADATA_VALUE_TYPES):
            # §21/§22: no nested dict/list/bytes/arbitrary object — only
            # JSON primitives.
            raise AuditValidationError(f"metadata value for {key_clean!r} must be a str/int/float/bool/None.")
        if isinstance(value, str):
            value = _clean_string(value, settings.max_metadata_value_length, f"metadata[{key_clean}]")
        cleaned[key_clean] = value
    return cleaned


def build_event(
    settings: AuditSettings,
    *,
    event_type: str,
    actor_type: str,
    actor_id: str | None,
    issuer: str | None,
    request_id: str | None,
    operation: str,
    resource_type: str | None,
    resource_id: str | None,
    result: str,
    decision: str | None = None,
    reason_code: str | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    """§70: rejects malformed events outright — never silently coerces an
    attacker/caller-controlled value into something "close enough."""
    if event_type not in ALL_EVENT_TYPES and event_type not in RESERVED_FOR_FUTURE_USE:
        raise AuditValidationError(f"Unknown event_type: {event_type!r}")
    if actor_type not in VALID_ACTOR_TYPES:
        raise AuditValidationError(f"Unknown actor_type: {actor_type!r}")
    if result not in VALID_RESULTS:
        raise AuditValidationError(f"Unknown result: {result!r}")
    if decision is not None and decision not in VALID_DECISIONS:
        raise AuditValidationError(f"Unknown decision: {decision!r}")

    event = AuditEvent(
        event_id=str(uuid.uuid4()),  # §27: unpredictable, never incrementing/timestamp-derived
        timestamp=datetime.now(timezone.utc).isoformat(),  # §28/§73/§74: server clock, UTC, never client-supplied
        schema_version=SCHEMA_VERSION,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=_clean_optional_string(actor_id, MAX_ACTOR_ID_LENGTH, "actor_id"),
        issuer=_clean_optional_string(issuer, MAX_ISSUER_LENGTH, "issuer"),
        request_id=_clean_optional_string(request_id, MAX_REQUEST_ID_LENGTH, "request_id"),
        operation=_clean_string(operation, MAX_OPERATION_LENGTH, "operation"),
        resource_type=_clean_optional_string(resource_type, MAX_RESOURCE_TYPE_LENGTH, "resource_type"),
        resource_id=_clean_optional_string(resource_id, MAX_RESOURCE_ID_LENGTH, "resource_id"),
        result=result,
        decision=decision,
        reason_code=_clean_optional_string(reason_code, MAX_REASON_CODE_LENGTH, "reason_code"),
        metadata=_validate_metadata(metadata or {}, settings),
    )

    # §23: whole-event size bound, checked last against the fully-built,
    # already-individually-bounded event — belt and suspenders against a
    # combination of many near-max-length fields adding up.
    import json

    serialized_size = len(
        json.dumps(
            {
                "event_id": event.event_id, "timestamp": event.timestamp, "event_type": event.event_type,
                "actor_type": event.actor_type, "actor_id": event.actor_id, "issuer": event.issuer,
                "request_id": event.request_id, "operation": event.operation, "resource_type": event.resource_type,
                "resource_id": event.resource_id, "result": event.result, "decision": event.decision,
                "reason_code": event.reason_code, "metadata": event.metadata,
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )
    if serialized_size > settings.max_event_bytes:
        raise AuditValidationError(f"Audit event exceeds the {settings.max_event_bytes}-byte limit.")

    return event
