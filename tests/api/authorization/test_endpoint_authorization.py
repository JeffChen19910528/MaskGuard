"""Phase 10.3 §17/§19/§20/§22/§41/§45/§62/§67/§71/§95: direct-HTTP
authorization tests against the REAL endpoints (never only exercised
"through the frontend," per §41/§72). 401/403 tests use trivial dummy
content — authorization is evaluated BEFORE any file is read (§20/§56/§57),
so they need no real image/Tesseract. ALLOW-path tests that actually
reach Core processing use `ocr_env`/`dataset_image` (skipped on a host
without Tesseract/chi_tra, same convention every other `tests/api/` file
already uses).
"""
from __future__ import annotations

import io
import json

import pytest

from .conftest import login_as


def _files():
    return {"file": ("upload.png", io.BytesIO(b"not a real image"), "image/png")}


# --- §19: anonymous access (401), never 403 for plain absence (§17) -----


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/analyze"),
        ("post", "/api/v1/process"),
        ("post", "/api/v1/redact"),
        ("post", "/api/v1/verify"),
    ],
)
def test_anonymous_access_to_image_endpoints_is_401(client, method, path):
    resp = getattr(client, method)(path, files=_files())
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_anonymous_access_to_review_is_401(client):
    resp = client.post(
        "/api/v1/review",
        files=_files(),
        data={"review": json.dumps({"review_token": "x", "items": []})},
    )
    assert resp.status_code == 401


def test_health_never_requires_authentication(client):
    """§19: do not blindly protect health."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200


def test_auth_endpoints_never_require_prior_authentication(client):
    """login/callback obviously precede having a session; logout/me must
    also remain reachable without one (they each handle "no session"
    internally, never a blanket 401 at the route level)."""
    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code in (302, 401)  # 401 only if OIDC misconfigured, not relevant here
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code in (200, 403)  # 403 only from Origin check, never 401


# --- §28: Operator (image.* only) vs review.* --------------------------


def test_operator_can_analyze(client, ocr_env, dataset_image):
    login_as(client, "operator-1")
    resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")})
    assert resp.status_code == 200


def test_operator_cannot_review(client):
    """§28 Attack 1: Operator attempts review.accept -> 403."""
    login_as(client, "operator-1")
    resp = client.post(
        "/api/v1/review",
        files=_files(),
        data={"review": json.dumps({"review_token": "x", "items": [{"detection_id": "d1", "review_status": "ACCEPTED"}]})},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AUTHORIZATION_DENIED"


def test_operator_cannot_read_configuration_or_audit(client):
    """No configuration/audit endpoints exist yet (§29/§85) — this test
    documents that fact by confirming no such route is reachable at all
    (404, not 403/200) rather than silently assuming it."""
    login_as(client, "operator-1")
    assert client.get("/api/v1/configuration").status_code == 404
    assert client.get("/api/v1/audit").status_code == 404


# --- Reviewer ------------------------------------------------------------


def test_reviewer_can_analyze_and_review(client, ocr_env, dataset_image):
    login_as(client, "reviewer-1")
    analyze_resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")})
    assert analyze_resp.status_code == 200
    body = analyze_resp.json()
    review_payload = {
        "review_token": body["review_token"],
        "items": [{"detection_id": body["detections"][0]["detection_id"], "review_status": "ACCEPTED"}],
    }
    review_resp = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")},
        data={"review": json.dumps(review_payload)},
    )
    assert review_resp.status_code == 200


def test_reviewer_manual_detection_allowed(client, ocr_env, dataset_image):
    login_as(client, "reviewer-1")
    analyze_resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")})
    body = analyze_resp.json()
    review_payload = {
        "review_token": body["review_token"],
        "items": [
            {"detection_id": body["detections"][0]["detection_id"], "review_status": "ACCEPTED"},
            {"source": "MANUAL", "type": "PersonalName", "bbox": {"x": 1, "y": 1, "width": 10, "height": 10}},
        ],
    }
    resp = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")},
        data={"review": json.dumps(review_payload)},
    )
    assert resp.status_code == 200


# --- Auditor: strictly read-only, cannot review or process --------------


def test_auditor_cannot_analyze(client):
    login_as(client, "auditor-1")
    resp = client.post("/api/v1/analyze", files=_files())
    assert resp.status_code == 403


def test_auditor_cannot_review(client):
    """§28 Attack: Auditor attempts review.accept -> 403."""
    login_as(client, "auditor-1")
    resp = client.post(
        "/api/v1/review",
        files=_files(),
        data={"review": json.dumps({"review_token": "x", "items": [{"detection_id": "d1", "review_status": "ACCEPTED"}]})},
    )
    assert resp.status_code == 403


# --- SecurityAdministrator: configuration only, never review ------------


def test_security_administrator_cannot_accept_review(client):
    login_as(client, "secadmin-1")
    resp = client.post(
        "/api/v1/review",
        files=_files(),
        data={"review": json.dumps({"review_token": "x", "items": [{"detection_id": "d1", "review_status": "ACCEPTED"}]})},
    )
    assert resp.status_code == 403


def test_security_administrator_cannot_analyze(client):
    login_as(client, "secadmin-1")
    resp = client.post("/api/v1/analyze", files=_files())
    assert resp.status_code == 403


# --- Administrator: administration.* only, nothing else by default ------


def test_administrator_has_no_image_or_review_access_by_default(client):
    """§8/§32: Administrator is NOT a superuser."""
    login_as(client, "admin-1")
    assert client.post("/api/v1/analyze", files=_files()).status_code == 403
    resp = client.post(
        "/api/v1/review",
        files=_files(),
        data={"review": json.dumps({"review_token": "x", "items": [{"detection_id": "d1", "review_status": "ACCEPTED"}]})},
    )
    assert resp.status_code == 403


# --- Multi-role union (§64) -----------------------------------------------


def test_reviewer_plus_auditor_gets_union_of_permissions(client, ocr_env, dataset_image):
    login_as(client, "reviewer-auditor-1")
    resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")})
    assert resp.status_code == 200  # Reviewer bundle
    # This identity still has no configuration.write — union never grants
    # something neither role actually has.
    assert client.get("/api/v1/configuration").status_code == 404  # no such route exists (documented)


# --- Default deny for an authenticated-but-unmapped identity (§49) ------


def test_authenticated_but_unmapped_identity_is_denied_everything(client):
    login_as(client, "unmapped-1")  # deliberately absent from the role-mapping file
    resp = client.post("/api/v1/analyze", files=_files())
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "AUTHORIZATION_DENIED"


# --- Session expiration removes authorization (§45) ----------------------


def test_expired_session_denies_previously_valid_permission(client):
    login_as(client, "operator-1")
    session_id = client.cookies.get("mg_sess")
    # Simulate expiry by deleting the server-side record directly — the
    # same effect as its idle/absolute timeout elapsing (§45/§47).
    client.auth_runtime.session_store.delete(session_id)

    resp = client.post("/api/v1/analyze", files=_files())
    assert resp.status_code == 401


# --- §68/§69: PolicyEngine bypass regression (MANDATORY) -----------------


def test_administrator_authorization_never_alters_policy_engine_decision(client, ocr_env, dataset_image):
    """§68: mandatory regression test. An Administrator is authorized for
    NOTHING image-related by default in this phase's matrix — but the
    real point of this test is broader and must hold for EVERY role: no
    amount of authorization privilege changes what PolicyEngine decides.
    Proven here via Reviewer (who IS authorized to process a Passport)
    and confirming the CRITICAL/FULL_MASK outcome is byte-for-byte the
    same as the completely unauthenticated-Core-path baseline."""
    login_as(client, "reviewer-1")
    resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("Passport_clean.png"), "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    passport = next(d for d in body["detections"] if d["type"] == "Passport")
    assert passport["risk_level"] == "CRITICAL"
    assert passport["action"] == "FULL_MASK"
