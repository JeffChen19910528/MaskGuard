"""Phase 10.3 §14/§27/§42-44/§95: claim/role/permission spoofing and the
cross-user review-token attack — every one of these must fail, using the
REAL authenticated server-side session, never a client-supplied value.
"""
from __future__ import annotations

import json

import pytest

from .conftest import login_as


def _files():
    import io

    return {"file": ("upload.png", io.BytesIO(b"not a real image"), "image/png")}


# --- §42/§43: role/permission spoofing via headers/JSON/cookies ----------


def test_forged_x_role_header_has_no_effect(client):
    login_as(client, "operator-1")  # Operator: no review.* permission
    resp = client.post(
        "/api/v1/review",
        files=_files(),
        data={"review": json.dumps({"review_token": "x", "items": [{"detection_id": "d1", "review_status": "ACCEPTED"}]})},
        headers={"X-Role": "Administrator", "X-User": "admin", "X-Permission": "review.accept"},
    )
    assert resp.status_code == 403  # still denied — headers are never consulted for authorization


def test_forged_role_in_json_body_has_no_effect(client):
    """§42: a role/permission field embedded in the review JSON body must
    be silently ignored — `ReviewItemRequest`/`ReviewSubmissionRequest`
    (Phase 8.3) have no such field to begin with, and this module never
    reads authorization data from request content regardless."""
    login_as(client, "operator-1")
    payload = {
        "review_token": "x",
        "role": "Administrator",
        "permission": "review.accept",
        "items": [{"detection_id": "d1", "review_status": "ACCEPTED", "role": "Administrator"}],
    }
    resp = client.post("/api/v1/review", files=_files(), data={"review": json.dumps(payload)})
    assert resp.status_code == 403


def test_forged_session_cookie_is_rejected(client):
    """§44: a client-forged (unknown) session id must never be treated as
    a trusted identity — the session store has no record for it, so it
    resolves to "no identity," not to whatever the cookie value implies."""
    client.cookies.set("mg_sess", "forged-session-id-attacker-controlled")
    resp = client.post("/api/v1/analyze", files=_files())
    assert resp.status_code == 401


def test_another_users_valid_session_cookie_cannot_be_reused_for_different_permissions(client, ocr_env, dataset_image):
    """A more realistic variant of cookie spoofing: an Operator cannot
    simply SET their cookie to a value that happens to look like it could
    be someone else's — session ids are unguessable (Phase 10.2 §75), so
    this test's real assertion is that a random guess never resolves to
    anyone's real session."""
    login_as(client, "operator-1")
    real_cookie_shape_but_wrong = "a" * 43  # same length class as a real secrets.token_urlsafe(32) value
    client.cookies.set("mg_sess", real_cookie_shape_but_wrong)
    resp = client.post("/api/v1/analyze", files=_files())
    assert resp.status_code == 401  # a guessed value is not the real session and grants nothing


# --- §10/§13: self-privilege-escalation surface -------------------------


def test_no_role_or_permission_assignment_endpoint_exists(client):
    """§10: `POST /roles`/`POST /permissions` must not exist at all."""
    login_as(client, "admin-1")
    assert client.post("/api/v1/roles", json={"role": "Administrator"}).status_code == 404
    assert client.post("/api/v1/permissions", json={"permission": "administration.write"}).status_code == 404


# --- §25-27: cross-user review-token attack (mandatory) ------------------


def test_cross_user_review_token_use_is_rejected(client, ocr_env, dataset_image):
    """§27: User A's review token, presented by User B (a DIFFERENT
    authenticated identity that otherwise DOES hold review.accept), must
    be rejected — token possession alone must not grant another user's
    review authority."""
    # User A (reviewer-1) analyzes and receives a token bound to THEIR identity.
    login_as(client, "reviewer-1")
    analyze_resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")})
    assert analyze_resp.status_code == 200
    body = analyze_resp.json()
    stolen_token = body["review_token"]
    detection_id = body["detections"][0]["detection_id"]

    # User B (reviewer-auditor-1) — a DIFFERENT identity, but one that
    # ALSO holds review.accept — attempts to redeem User A's token.
    login_as(client, "reviewer-auditor-1")
    resp = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")},
        data={"review": json.dumps({"review_token": stolen_token, "items": [{"detection_id": detection_id, "review_status": "ACCEPTED"}]})},
    )
    # Not a 403 (User B DOES have review.accept in general) — the token
    # itself is refused because it belongs to a different identity.
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_REVIEW"


def test_same_user_can_still_use_their_own_token(client, ocr_env, dataset_image):
    """Sanity/negative-control counterpart to the attack test above —
    proves the binding rejects a DIFFERENT identity specifically, not
    every submission."""
    login_as(client, "reviewer-1")
    analyze_resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")})
    body = analyze_resp.json()
    resp = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")},
        data={
            "review": json.dumps(
                {"review_token": body["review_token"], "items": [{"detection_id": body["detections"][0]["detection_id"], "review_status": "ACCEPTED"}]}
            )
        },
    )
    assert resp.status_code == 200
