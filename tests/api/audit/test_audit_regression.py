"""Phase 10.4 §109/§110: MANDATORY regression tests. A failure here is
FAIL for the whole phase (§129).
"""
from __future__ import annotations

from .conftest import login_as


def test_policy_engine_unaffected_by_audit_mandatory(client, ocr_env, dataset_image):
    """§109: authorized Reviewer processes a real Passport image; audit
    being active must not change RiskEngine/PolicyEngine's decision —
    still CRITICAL/FULL_MASK, still passes verification."""
    login_as(client, "reviewer-1")
    resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("Passport_clean.png"), "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    passport = next(d for d in body["detections"] if d["type"] == "Passport")
    assert passport["risk_level"] == "CRITICAL"
    assert passport["action"] == "FULL_MASK"

    redact_resp = client.post("/api/v1/redact", files={"file": ("upload.png", dataset_image("Passport_clean.png"), "image/png")})
    assert redact_resp.status_code == 200
    verify_resp = client.post("/api/v1/verify", files={"file": ("out.png", redact_resp.content, "image/png")})
    assert verify_resp.status_code == 200
    assert verify_resp.json()["clean"] is True


def test_authorization_regression_mandatory(client):
    """§110: exact three-way check the phase brief specifies."""
    login_as(client, "operator-1")
    assert client.get("/api/v1/audit").status_code == 403

    login_as(client, "auditor-1")
    assert client.get("/api/v1/audit").status_code == 200

    resp = client.get("/api/v1/audit")  # still authenticated as auditor-1; verify anonymous separately below
    assert resp.status_code == 200


def test_anonymous_audit_access_401_mandatory(client):
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 401
