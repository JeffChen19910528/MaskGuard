"""Phase 10.6 §13/§14/§15/§16/§17/§61/§62/§65/§66/§67: MANDATORY
cross-instance session tests, real HTTP against two independently-wired
"nodes" sharing one real Redis."""
from __future__ import annotations

from .conftest import cross_node_login, login_as


def test_login_on_a_then_me_on_b_mandatory(two_nodes):
    """§13/§61: MANDATORY. Login through Node A, then /auth/me through
    Node B — same identity, no reauthentication required."""
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "operator-1")

    me_a = node_a.get("/api/v1/auth/me")
    assert me_a.json()["authenticated"] is True

    session_cookie = node_a.cookies.get("mg_sess")
    node_b.cookies.set("mg_sess", session_cookie)  # the ONE thing a real browser does automatically
    me_b = node_b.get("/api/v1/auth/me")
    assert me_b.status_code == 200
    assert me_b.json()["authenticated"] is True
    assert me_b.json()["subject"] == me_a.json()["subject"]


def test_login_on_a_logout_on_b_then_a_unauthenticated_mandatory(two_nodes):
    """§14/§62/§149: MANDATORY. Login A, logout B, check A -> invalid
    everywhere."""
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "operator-1")
    session_cookie = node_a.cookies.get("mg_sess")
    node_b.cookies.set("mg_sess", session_cookie)

    logout_resp = node_b.post("/api/v1/auth/logout", headers={"Origin": "https://maskguard.test.invalid"})
    assert logout_resp.status_code == 200

    me_a = node_a.get("/api/v1/auth/me")
    assert me_a.json()["authenticated"] is False


def test_session_hijacking_same_cookie_both_nodes_same_identity(two_nodes):
    """§16: a valid session cookie presented to either node yields the
    SAME authenticated identity."""
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "reviewer-1")
    session_cookie = node_a.cookies.get("mg_sess")
    node_b.cookies.set("mg_sess", session_cookie)

    assert node_a.get("/api/v1/auth/me").json()["subject"] == node_b.get("/api/v1/auth/me").json()["subject"]


def test_modified_cookie_unauthenticated_on_both_nodes(two_nodes):
    """§16: a tampered cookie value is unauthenticated everywhere."""
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "operator-1")
    real_cookie = node_a.cookies.get("mg_sess")
    tampered = real_cookie[:-4] + "xxxx"
    node_a.cookies.set("mg_sess", tampered)
    node_b.cookies.set("mg_sess", tampered)

    assert node_a.get("/api/v1/auth/me").json()["authenticated"] is False
    assert node_b.get("/api/v1/auth/me").json()["authenticated"] is False


def test_session_cookie_replay_after_logout_fails_on_both_nodes(two_nodes):
    """§17: replaying the OLD cookie after logout fails on every node."""
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "operator-1")
    old_cookie = node_a.cookies.get("mg_sess")
    node_a.post("/api/v1/auth/logout", headers={"Origin": "https://maskguard.test.invalid"})

    node_b.cookies.set("mg_sess", old_cookie)
    assert node_b.get("/api/v1/auth/me").json()["authenticated"] is False
    node_a.cookies.set("mg_sess", old_cookie)
    assert node_a.get("/api/v1/auth/me").json()["authenticated"] is False


def test_login_a_callback_b_no_sticky_session_required(two_nodes):
    """§60/§116-117: login initiated on Node A, callback completed on
    Node B (no sticky session) — still succeeds, because the pending
    OIDC transaction is ALSO Redis-backed (Phase 10.6 addition beyond
    the letter of the state catalog, justified in session.py's own
    docstring)."""
    node_a, node_b, token_options = two_nodes
    callback = cross_node_login(node_a, node_b, token_options, "operator-1")
    session_cookie = callback.cookies.get("mg_sess")
    assert session_cookie
    node_b.cookies.set("mg_sess", session_cookie)
    assert node_b.get("/api/v1/auth/me").json()["authenticated"] is True


def test_authorization_regression_identical_across_nodes(two_nodes):
    """§65/§66/§67: every role produces identical 401/403/200 on both
    nodes for the same authenticated state (AUDIT_ENABLED left unset
    here — this test only needs a permission decision, not the audit
    store; §65 is covered end-to-end by the audit-specific test file)."""
    node_a, node_b, token_options = two_nodes
    for subject, expect_image_access in (
        ("operator-1", True), ("reviewer-1", True),
        ("secadmin-1", False), ("auditor-1", False), ("admin-1", False),
    ):
        login_as(node_a, token_options, subject)
        session_cookie = node_a.cookies.get("mg_sess")
        node_b.cookies.set("mg_sess", session_cookie)

        tiny_file = {"file": ("x.png", b"not-a-real-image", "image/png")}
        # Rate limit runs before auth-content validation; use a distinct
        # analyze call per subject so capacity=3 isn't exhausted across
        # the loop — each subject gets its own identity-scoped bucket.
        status_a = node_a.post("/api/v1/analyze", files=tiny_file).status_code
        status_b = node_b.post("/api/v1/analyze", files=tiny_file).status_code
        assert status_a == status_b
        if expect_image_access:
            assert status_a == 415  # authorized, rejected only for bad file content
        else:
            assert status_a == 403
