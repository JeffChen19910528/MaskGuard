"""Phase 10.3 §5/§6/§8: the permission namespace and default role->permission
bundles. Permission strings are the actual authorization primitive
(§4) — route code checks `"image.analyze" in permissions`, never
`role == "Operator"`.

Role->permission BUNDLES are a stable, application-defined constant (code,
not configuration) — this is the part of the model that "allows future
custom enterprise roles without rewriting endpoint logic" refers to
(§4/§7): endpoints only ever check permissions, so adding/adjusting a
role's bundle here never touches route code. WHO gets which role is the
separate, deployment-specific, configuration-driven question answered by
`role_config.py` (§11/§13/§52).
"""
from __future__ import annotations

# --- Permission namespace (§5/§6): resource.action, defined only where a
# real operation exists (§5: "do not add permissions that have no real
# operation").
IMAGE_ANALYZE = "image.analyze"
IMAGE_REDACT = "image.redact"
IMAGE_VERIFY = "image.verify"
REVIEW_VIEW = "review.view"
REVIEW_ACCEPT = "review.accept"
REVIEW_REJECT = "review.reject"
REVIEW_MANUAL_DETECT = "review.manual_detect"
CONFIGURATION_READ = "configuration.read"
CONFIGURATION_WRITE = "configuration.write"
AUDIT_READ = "audit.read"
ADMINISTRATION_READ = "administration.read"
ADMINISTRATION_WRITE = "administration.write"

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY,
        REVIEW_VIEW, REVIEW_ACCEPT, REVIEW_REJECT, REVIEW_MANUAL_DETECT,
        CONFIGURATION_READ, CONFIGURATION_WRITE,
        AUDIT_READ,
        ADMINISTRATION_READ, ADMINISTRATION_WRITE,
    }
)

#: §7/§8/§9: the initial role set, reconciled against
#: docs/enterprise-authorization-architecture.md. Least-privilege (§48):
#: no role is granted a permission it has no documented operational need
#: for.
#:
#: - Operator: ordinary processing only. NOT review.* (§35) — an Operator
#:   submitting their own images has no inherent need to adjudicate OTHER
#:   people's review queues; a deployment that wants one person doing
#:   both assigns them both `Operator` and `Reviewer` (§64, union).
#: - Reviewer: review.* PLUS image.* — a reviewer must be able to call
#:   /analyze to produce the detections/review_token they then act on
#:   (the existing Phase 8.3 flow: analyze -> review is one continuous
#:   operator-facing task). NOT configuration.*/audit.* (§34: least
#:   privilege — reviewing content has no bearing on changing security
#:   configuration or reading the audit trail).
#: - SecurityAdministrator: configuration.* only (§36) — explicitly NOT
#:   review.accept/reject: configuration privilege must not silently
#:   become review privilege (§36's own explicit instruction), preserving
#:   separation of duties between "sets the rules" and "applies them to
#:   specific content."
#: - Auditor: audit.read only (§33) — strictly read-only; no
#:   configuration.write, no review.*.
#: - Administrator: administration.read/write ONLY (§8/§32) — deliberately
#:   NOT image.*/review.*/configuration.*/audit.* by default. This is the
#:   least-privilege choice explicitly invited by §8 ("do not automatically
#:   give Administrator every permission... prefer least privilege"):
#:   `Administrator` here means "owns the administrative/deployment plane"
#:   (docs/adr/ADR-010-admin-plane.md's future scope — e.g. deployment
#:   settings, once such operations exist), not "can do everything every
#:   other role can do." An organization needing one identity with every
#:   capability assigns that identity ALL FIVE roles explicitly (§64's
#:   union-of-permissions model) — an intentional, visible configuration
#:   choice rather than an implicit default baked into one role's name.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "Operator": frozenset({IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY}),
    "Reviewer": frozenset(
        {IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY, REVIEW_VIEW, REVIEW_ACCEPT, REVIEW_REJECT, REVIEW_MANUAL_DETECT}
    ),
    "SecurityAdministrator": frozenset({CONFIGURATION_READ, CONFIGURATION_WRITE}),
    "Auditor": frozenset({AUDIT_READ}),
    "Administrator": frozenset({ADMINISTRATION_READ, ADMINISTRATION_WRITE}),
}

KNOWN_ROLES: frozenset[str] = frozenset(ROLE_PERMISSIONS.keys())


def permissions_for_roles(roles: frozenset[str]) -> frozenset[str]:
    """§64: union of every explicitly-granted role's bundle. An unknown
    role name contributes NOTHING (§49 default deny) — never raises here;
    validation of the role NAME happens at configuration-load time
    (`role_config.py`), so by the time this function runs every name in
    `roles` is already known-good, but this function stays defensive
    (`.get(role, frozenset())`) rather than assuming that invariant holds
    forever."""
    result: set[str] = set()
    for role in roles:
        result |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(result)
