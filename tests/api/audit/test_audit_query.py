"""Phase 10.4 §38/§39/§40/§116: query API filters, bounds, and abuse
resistance.
"""
from __future__ import annotations

from .conftest import login_as


def test_query_page_size_is_bounded(client):
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit?limit=999999")
    assert resp.status_code == 200
    # Bounded server-side to AuditSettings.max_query_page_size (default
    # 200) regardless of what the client asked for.
    assert resp.json()["count"] <= 200


def test_query_time_range_is_bounded(client):
    login_as(client, "auditor-1")
    # `params=` (not string-concatenated into the URL) so httpx correctly
    # percent-encodes the `+` in the timezone offset — a raw `+` in a URL
    # query string means literal space, not a `+` character.
    resp = client.get("/api/v1/audit", params={"since": "2000-01-01T00:00:00+00:00"})
    assert resp.status_code == 200  # bounded server-side, not rejected — see routes.py


def test_malformed_since_is_rejected(client):
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit?since=not-a-real-date")
    assert resp.status_code == 422


def test_sql_injection_string_in_filter_is_safely_ignored_not_executed(client):
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit?actor_id=" + "'; DROP TABLE audit_events; --")
    assert resp.status_code == 200  # parameterized query — treated as a literal, no error, no table dropped
    # Confirm the table still exists / still queryable normally.
    resp2 = client.get("/api/v1/audit")
    assert resp2.status_code == 200


def test_query_response_uses_typed_schema_only(client):
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit")
    body = resp.json()
    if body["events"]:
        event = body["events"][0]
        assert set(event.keys()) == {
            "event_id", "timestamp", "schema_version", "event_type", "actor_type", "actor_id",
            "issuer", "request_id", "operation", "resource_type", "resource_id", "result",
            "decision", "reason_code", "metadata", "hash", "prev_hash",
        }


def test_filter_by_event_type(client):
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit?event_type=AUTH_LOGIN_SUCCESS")
    body = resp.json()
    assert all(e["event_type"] == "AUTH_LOGIN_SUCCESS" for e in body["events"])


def test_filter_by_unknown_event_type_returns_empty_not_error(client):
    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit?event_type=NOT_A_REAL_TYPE")
    assert resp.status_code == 200
    assert resp.json()["events"] == []
