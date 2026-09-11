"""Phase 10.4 §7/§27/§28/§65/§71: the typed audit event. Every field is
justified by §4's WHO/WHAT/WHEN/RESULT principle plus explicitly-useful
correlation context — nothing speculative.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = 1

#: §71: strict maximum lengths — never megabyte-long fields.
MAX_ACTOR_ID_LENGTH = 256
MAX_ISSUER_LENGTH = 256
MAX_REQUEST_ID_LENGTH = 128
MAX_OPERATION_LENGTH = 64
MAX_RESOURCE_TYPE_LENGTH = 32
MAX_RESOURCE_ID_LENGTH = 128
MAX_REASON_CODE_LENGTH = 64

ACTOR_TYPE_USER = "user"
ACTOR_TYPE_ANONYMOUS = "anonymous"
ACTOR_TYPE_SYSTEM = "system"
VALID_ACTOR_TYPES = frozenset({ACTOR_TYPE_USER, ACTOR_TYPE_ANONYMOUS, ACTOR_TYPE_SYSTEM})

RESULT_SUCCESS = "SUCCESS"
RESULT_FAILURE = "FAILURE"
RESULT_DENIED = "DENIED"
VALID_RESULTS = frozenset({RESULT_SUCCESS, RESULT_FAILURE, RESULT_DENIED})

DECISION_ALLOW = "ALLOW"
DECISION_DENY = "DENY"
VALID_DECISIONS = frozenset({DECISION_ALLOW, DECISION_DENY})

#: §22: only these JSON-primitive types may appear as metadata VALUES —
#: never bytes, never a nested dict/list (§21/§22: "no nested arbitrary
#: objects").
_ALLOWED_METADATA_VALUE_TYPES = (str, int, float, bool, type(None))


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    timestamp: str  # ISO 8601 UTC, e.g. "2026-09-10T12:00:00.000000+00:00" (§73)
    schema_version: int
    event_type: str
    actor_type: str
    actor_id: str | None
    issuer: str | None
    request_id: str | None
    operation: str
    resource_type: str | None
    resource_id: str | None
    result: str
    decision: str | None
    reason_code: str | None
    metadata: dict[str, str | int | float | bool | None] = field(default_factory=dict)
    #: Integrity chain (§30) — populated by `storage.py` at write time,
    #: not by the caller.
    prev_hash: str | None = None
    hash: str | None = None
