"""Phase 10.3 §62/§63: the complete role x permission matrix, tested
exhaustively at the resolution-logic level (fast, deterministic) — every
one of the 5 roles against every one of the 12 permissions gets an
explicit ALLOW/DENY assertion, no ambiguous cases left untested.
"""
from __future__ import annotations

import pytest

from maskguard.api.authorization.permissions import (
    ADMINISTRATION_READ, ADMINISTRATION_WRITE, ALL_PERMISSIONS, AUDIT_READ,
    CONFIGURATION_READ, CONFIGURATION_WRITE, IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY,
    REVIEW_ACCEPT, REVIEW_MANUAL_DETECT, REVIEW_REJECT, REVIEW_VIEW,
    ROLE_PERMISSIONS, permissions_for_roles,
)

# role -> set of permissions it MUST have (everything else in
# ALL_PERMISSIONS is implicitly DENY for that role — checked below).
EXPECTED_ALLOW = {
    "Operator": {IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY},
    "Reviewer": {IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY, REVIEW_VIEW, REVIEW_ACCEPT, REVIEW_REJECT, REVIEW_MANUAL_DETECT},
    "SecurityAdministrator": {CONFIGURATION_READ, CONFIGURATION_WRITE},
    "Auditor": {AUDIT_READ},
    "Administrator": {ADMINISTRATION_READ, ADMINISTRATION_WRITE},
}


@pytest.mark.parametrize("role,expected_allow", EXPECTED_ALLOW.items())
def test_role_permission_matrix_is_exact(role, expected_allow):
    """Every permission not explicitly expected is explicitly denied —
    no permission is ambiguous (§62)."""
    granted = permissions_for_roles(frozenset({role}))
    assert granted == frozenset(expected_allow), f"{role}: expected exactly {expected_allow}, got {granted}"
    for permission in ALL_PERMISSIONS - expected_allow:
        assert permission not in granted, f"{role} must NOT have {permission}"


def test_operator_cannot_review():
    granted = permissions_for_roles(frozenset({"Operator"}))
    assert REVIEW_ACCEPT not in granted
    assert REVIEW_REJECT not in granted
    assert REVIEW_MANUAL_DETECT not in granted
    assert CONFIGURATION_WRITE not in granted
    assert AUDIT_READ not in granted


def test_auditor_is_strictly_read_only():
    granted = permissions_for_roles(frozenset({"Auditor"}))
    assert granted == frozenset({AUDIT_READ})


def test_security_administrator_cannot_review():
    """§36: configuration privilege must not silently become review
    privilege."""
    granted = permissions_for_roles(frozenset({"SecurityAdministrator"}))
    assert REVIEW_ACCEPT not in granted
    assert REVIEW_REJECT not in granted


def test_administrator_does_not_get_everything_by_default():
    """§8/§32: no magical superuser — Administrator is scoped to the
    administrative plane only."""
    granted = permissions_for_roles(frozenset({"Administrator"}))
    assert granted == frozenset({ADMINISTRATION_READ, ADMINISTRATION_WRITE})
    assert IMAGE_ANALYZE not in granted
    assert REVIEW_ACCEPT not in granted
    assert CONFIGURATION_WRITE not in granted
    assert AUDIT_READ not in granted


def test_multiple_roles_union_not_string_matching():
    """§64: Reviewer + Auditor gets the UNION of both bundles — never
    accidentally matches something like 'Administrator' through partial
    string comparison."""
    granted = permissions_for_roles(frozenset({"Reviewer", "Auditor"}))
    assert granted == frozenset(EXPECTED_ALLOW["Reviewer"]) | frozenset({AUDIT_READ})
    assert ADMINISTRATION_WRITE not in granted


def test_unknown_role_contributes_nothing():
    """§49: an unknown role name (should never occur post-config-validation,
    but the resolver stays defensive) grants zero permissions rather than
    raising or defaulting to something else."""
    granted = permissions_for_roles(frozenset({"NotARealRole"}))
    assert granted == frozenset()


def test_no_roles_at_all_is_default_deny():
    assert permissions_for_roles(frozenset()) == frozenset()


def test_every_declared_permission_is_granted_to_at_least_one_role():
    """§5: sanity check that the matrix itself is coherent — no permission
    silently orphaned with no role able to exercise it."""
    all_granted = frozenset().union(*(frozenset(v) for v in EXPECTED_ALLOW.values()))
    assert all_granted == ALL_PERMISSIONS


def test_role_permissions_constant_matches_expected_allow():
    for role, expected in EXPECTED_ALLOW.items():
        assert ROLE_PERMISSIONS[role] == frozenset(expected)
