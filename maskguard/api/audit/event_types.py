"""Phase 10.4 §9: a stable, closed event-type namespace. Every type here
is actually emitted somewhere (`service.py`'s callers) — none are
speculative/never-emitted (§9's own instruction).
"""
from __future__ import annotations

AUTH_LOGIN_SUCCESS = "AUTH_LOGIN_SUCCESS"
AUTH_LOGIN_FAILURE = "AUTH_LOGIN_FAILURE"
AUTH_LOGOUT = "AUTH_LOGOUT"
AUTH_SESSION_EXPIRED = "AUTH_SESSION_EXPIRED"

AUTHORIZATION_ALLOWED = "AUTHORIZATION_ALLOWED"
AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"

IMAGE_ANALYZE = "IMAGE_ANALYZE"
IMAGE_REDACT = "IMAGE_REDACT"
IMAGE_VERIFY = "IMAGE_VERIFY"

REVIEW_CREATED = "REVIEW_CREATED"
REVIEW_ACCEPTED = "REVIEW_ACCEPTED"
REVIEW_REJECTED = "REVIEW_REJECTED"
REVIEW_MANUAL_DETECTION = "REVIEW_MANUAL_DETECTION"

# §19/§48: no configuration-write API exists yet (Phase 10.3's own
# documented finding) — these two types are defined now, ready for the
# day such an endpoint ships, per §48's explicit instruction to "prepare
# the event model" without inventing an API solely to exercise it. Not
# emitted anywhere today.
CONFIGURATION_CHANGE = "CONFIGURATION_CHANGE"
SECURITY_CONFIGURATION_CHANGE = "SECURITY_CONFIGURATION_CHANGE"

# §42: audit-of-audit-access.
AUDIT_ACCESS = "AUDIT_ACCESS"

ALL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        AUTH_LOGIN_SUCCESS, AUTH_LOGIN_FAILURE, AUTH_LOGOUT, AUTH_SESSION_EXPIRED,
        AUTHORIZATION_ALLOWED, AUTHORIZATION_DENIED,
        IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY,
        REVIEW_CREATED, REVIEW_ACCEPTED, REVIEW_REJECTED, REVIEW_MANUAL_DETECTION,
        CONFIGURATION_CHANGE, SECURITY_CONFIGURATION_CHANGE,
        AUDIT_ACCESS,
    }
)

#: §9/§43: types NOT emitted anywhere in this phase — reserved for a
#: future configuration API, kept out of ALL_EVENT_TYPES's "actually
#: emitted" implication would be misleading, so they're tracked here
#: instead and validated the same way (still schema-valid to write, just
#: never triggered by any current code path).
RESERVED_FOR_FUTURE_USE: frozenset[str] = frozenset({CONFIGURATION_CHANGE, SECURITY_CONFIGURATION_CHANGE})
