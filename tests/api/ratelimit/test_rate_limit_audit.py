"""Phase 10.5 §22/§48/§49/§96: audit-query rate limiting. No Tesseract
needed — audit endpoints never touch Core."""
from __future__ import annotations

from maskguard.api.audit.config import get_audit_settings
from maskguard.api.audit.service import get_audit_store

from ..authorization.conftest import login_as
from .conftest import build_client


def _audit_client(monkeypatch, tmp_path, provider, **overrides):
    overrides.setdefault("AUDIT_ENABLED", "true")
    overrides.setdefault("AUDIT_INTEGRITY_KEY", "test-only-audit-integrity-key-32chars-min")
    overrides.setdefault("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()
    return build_client(monkeypatch, tmp_path, provider, **overrides)


def test_auditor_audit_query_rate_limited(monkeypatch, tmp_path, provider):
    client = _audit_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_AUDIT_QUERY_CAPACITY="3", RATE_LIMIT_AUDIT_QUERY_WINDOW_SECONDS="10",
    )
    login_as(client, "auditor-1")
    for _ in range(3):
        r = client.get("/api/v1/audit")
        assert r.status_code == 200
    r = client.get("/api/v1/audit")
    assert r.status_code == 429


def test_auditor_does_not_get_unlimited_querying(monkeypatch, tmp_path, provider):
    # §68: audit.read permission does not imply unlimited querying.
    client = _audit_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_AUDIT_QUERY_CAPACITY="2", RATE_LIMIT_AUDIT_QUERY_WINDOW_SECONDS="10",
    )
    login_as(client, "auditor-1")
    assert client.get("/api/v1/audit?limit=200").status_code == 200
    assert client.get("/api/v1/audit", params={"since": "2000-01-01T00:00:00+00:00"}).status_code == 200
    assert client.get("/api/v1/audit").status_code == 429


def test_integrity_endpoint_shares_audit_query_class(monkeypatch, tmp_path, provider):
    # §49: integrity checks share the same budget as queries (deliberate
    # simplification — "do not over-engineer").
    client = _audit_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_AUDIT_QUERY_CAPACITY="2", RATE_LIMIT_AUDIT_QUERY_WINDOW_SECONDS="10",
    )
    login_as(client, "auditor-1")
    assert client.get("/api/v1/audit").status_code == 200
    assert client.get("/api/v1/audit/integrity").status_code == 200
    r = client.get("/api/v1/audit/integrity")
    assert r.status_code == 429


def test_operator_still_gets_403_not_429_when_denied(monkeypatch, tmp_path, provider):
    # §24: authorization (403) is checked AFTER rate limiting passes —
    # a non-rate-limited but unauthorized caller still gets 403, not 429.
    client = _audit_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_AUDIT_QUERY_CAPACITY="5", RATE_LIMIT_AUDIT_QUERY_WINDOW_SECONDS="10",
    )
    login_as(client, "operator-1")
    r = client.get("/api/v1/audit")
    assert r.status_code == 403


def test_anonymous_still_gets_401_not_429_when_under_capacity(monkeypatch, tmp_path, provider):
    client = _audit_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_AUDIT_QUERY_CAPACITY="5", RATE_LIMIT_AUDIT_QUERY_WINDOW_SECONDS="10",
    )
    r = client.get("/api/v1/audit")
    assert r.status_code == 401
