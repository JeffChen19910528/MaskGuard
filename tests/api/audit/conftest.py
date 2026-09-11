"""Phase 10.4: fixtures for audit tests. Reuses Phase 10.3's mock-OIDC +
role-mapping machinery (`tests/api/authorization/conftest.py`) directly —
audit sits on top of authentication+authorization, not a parallel
identity system.
"""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from maskguard.api.app import create_app
from maskguard.api.audit.config import get_audit_settings
from maskguard.api.audit.service import get_audit_store
from maskguard.api.auth.config import get_auth_settings
from maskguard.api.auth.dependencies import AuthRuntime, _DiscoveryCache, get_auth_runtime
from maskguard.api.auth.discovery import OidcDiscoveryDocument
from maskguard.api.auth.session import InMemoryPendingTransactionStore, InMemorySessionStore
from maskguard.api.authorization.role_config import get_role_mapping
from maskguard.api.dependencies import get_service
from maskguard.api.ratelimit.config import get_rate_limit_settings
from maskguard.api.ratelimit.dependencies import get_rate_limiter

from ..auth.mock_provider import FakeKeyProvider, MockOidcProvider
from ..authorization.conftest import CLIENT_ID, ISSUER, REDIRECT_URI, _write_role_mapping_file
from ..authorization.conftest import login_as  # noqa: F401  (re-exported for test modules)


@pytest.fixture()
def provider() -> MockOidcProvider:
    return MockOidcProvider(issuer=ISSUER)


def _make_transport(provider: MockOidcProvider, token_options: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=provider.discovery_document())
        if request.url.path == "/token":
            id_token = provider.issue_id_token(
                audience=CLIENT_ID, nonce=token_options.get("nonce", "test-nonce"),
                subject=token_options.get("subject", "operator-1"),
            )
            return httpx.Response(200, json={"id_token": id_token, "token_type": "Bearer"})
        return httpx.Response(404, json={"error": "not_found"})

    return httpx.MockTransport(handler)


@pytest.fixture()
def client(monkeypatch, tmp_path, provider):
    role_mapping_path = _write_role_mapping_file(tmp_path)
    audit_db_path = str(tmp_path / "audit.db")

    monkeypatch.setenv("MASKGUARD_ENV", "development")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("OIDC_CLOCK_SKEW_SECONDS", "120")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("SESSION_ABSOLUTE_TIMEOUT_SECONDS", "28800")
    monkeypatch.setenv("AUTHZ_ROLE_MAPPING_FILE", role_mapping_path)
    monkeypatch.setenv("AUDIT_ENABLED", "true")
    monkeypatch.setenv("AUDIT_DB_PATH", audit_db_path)
    monkeypatch.setenv("AUDIT_INTEGRITY_KEY", "test-only-audit-integrity-key-32chars-min")
    get_auth_settings.cache_clear()
    get_role_mapping.cache_clear()
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()
    get_service.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()

    auth_settings = get_auth_settings()
    token_options: dict = {}
    runtime = AuthRuntime(
        settings=auth_settings,
        session_store=InMemorySessionStore(max_sessions=100),
        transaction_store=InMemoryPendingTransactionStore(max_transactions=100),
        http_client=httpx.AsyncClient(transport=_make_transport(provider, token_options)),
    )
    doc = OidcDiscoveryDocument(**provider.discovery_document())
    runtime._discovery_cache = _DiscoveryCache(document=doc, key_provider=FakeKeyProvider(provider), fetched_at=time.time())
    runtime.token_options = token_options  # type: ignore[attr-defined]

    app = create_app()
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.auth_runtime = runtime  # type: ignore[attr-defined]
        test_client.audit_db_path = audit_db_path  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    get_auth_settings.cache_clear()
    get_role_mapping.cache_clear()
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()
    get_service.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()
