"""Phase 10.4 §36/§41/§87/§110/§115: audit.read access control — direct
HTTP, real endpoints.
"""
from __future__ import annotations

from .conftest import login_as


def test_anonymous_audit_access_is_401(client):
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 401


def test_operator_audit_access_is_403(client):
    """§110/§28: mandatory authorization regression — Operator has no
    audit.read."""
    login_as(client, "operator-1")
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 403


def test_reviewer_audit_access_is_403(client):
    login_as(client, "reviewer-1")
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 403


def test_security_administrator_audit_access_is_403(client):
    login_as(client, "secadmin-1")
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 403


def test_auditor_audit_access_is_allowed(client):
    """§110/§41: mandatory — Auditor MUST be allowed."""
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert "events" in body and "count" in body


def test_administrator_audit_access_is_403(client):
    """§8/§32: Administrator has no audit.read by default (least privilege)."""
    login_as(client, "admin-1")
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 403


def test_integrity_endpoint_same_access_control(client):
    resp = client.get("/api/v1/audit/integrity")
    assert resp.status_code == 401

    login_as(client, "operator-1")
    assert client.get("/api/v1/audit/integrity").status_code == 403


def test_auditor_can_check_integrity(client):
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit/integrity")
    assert resp.status_code == 200
    assert resp.json()["integrity"] in ("PASS", "FAIL")


# --- §42: audit self-auditing ----------------------------------------------


def test_audit_access_itself_generates_an_audit_event(client):
    login_as(client, "auditor-1")
    client.get("/api/v1/audit")  # first call: reads whatever exists so far (likely just AUTH_LOGIN_SUCCESS)
    resp2 = client.get("/api/v1/audit?event_type=AUDIT_ACCESS")
    body = resp2.json()
    assert body["count"] >= 1
    assert all(e["event_type"] == "AUDIT_ACCESS" for e in body["events"])
    # §42: never the raw query string / full filter set — only safe fields.
    for e in body["events"]:
        assert e["metadata"].get("result_count") is not None
        assert "query_string" not in e["metadata"]
