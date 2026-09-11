"""Phase 10.3: fixtures for authorization (RBAC) tests. Builds on the
same mock-OIDC-provider approach Phase 10.2 established
(`tests/api/auth/mock_provider.py`, reused directly) but supports logging
in as MULTIPLE distinct test identities (one per role under test) via a
generated, temporary role-mapping YAML file.
"""
from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from maskguard.api.app import create_app
from maskguard.api.auth.config import get_auth_settings
from maskguard.api.auth.dependencies import AuthRuntime, _DiscoveryCache, get_auth_runtime
from maskguard.api.auth.discovery import OidcDiscoveryDocument
from maskguard.api.auth.session import InMemoryPendingTransactionStore, InMemorySessionStore
from maskguard.api.authorization.role_config import get_role_mapping
from maskguard.api.dependencies import get_service
from maskguard.api.ratelimit.config import get_rate_limit_settings
from maskguard.api.ratelimit.dependencies import get_rate_limiter

from ..auth.mock_provider import FakeKeyProvider, MockOidcProvider

ISSUER = "https://idp.test.invalid"
CLIENT_ID = "maskguard-client"
REDIRECT_URI = "https://maskguard.test.invalid/api/v1/auth/callback"

#: subject -> roles, used to generate the temp role-mapping file. Every
#: role under test gets its OWN subject so tests can log in as exactly
#: one role at a time (§62's matrix) without cross-contamination. Also
#: includes a MULTI-role identity (§64) and a deliberately-UNMAPPED
#: identity (§49 default deny for an authenticated-but-unknown user).
SUBJECT_ROLES = {
    "operator-1": ["Operator"],
    "reviewer-1": ["Reviewer"],
    "secadmin-1": ["SecurityAdministrator"],
    "auditor-1": ["Auditor"],
    "admin-1": ["Administrator"],
    "reviewer-auditor-1": ["Reviewer", "Auditor"],
    # "unmapped-1" deliberately has NO entry at all.
}


def _write_role_mapping_file(tmp_path) -> str:
    mappings = [{"issuer": ISSUER, "subject": subject, "roles": roles} for subject, roles in SUBJECT_ROLES.items()]
    path = tmp_path / "authz-roles.yaml"
    path.write_text(yaml.safe_dump({"mappings": mappings}), encoding="utf-8")
    return str(path)


@pytest.fixture()
def provider() -> MockOidcProvider:
    return MockOidcProvider(issuer=ISSUER)


def _make_transport(provider: MockOidcProvider, token_options: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=provider.discovery_document())
        if request.url.path == "/token":
            id_token = provider.issue_id_token(
                audience=CLIENT_ID,
                nonce=token_options.get("nonce", "test-nonce"),
                subject=token_options.get("subject", "operator-1"),
            )
            return httpx.Response(200, json={"id_token": id_token, "token_type": "Bearer"})
        return httpx.Response(404, json={"error": "not_found"})

    return httpx.MockTransport(handler)


@pytest.fixture()
def client(monkeypatch, tmp_path, provider):
    role_mapping_path = _write_role_mapping_file(tmp_path)

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
    get_auth_settings.cache_clear()
    get_role_mapping.cache_clear()
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
    runtime.token_options = token_options  # type: ignore[attr-defined]  # test-only

    app = create_app()
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.auth_runtime = runtime  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    get_auth_settings.cache_clear()
    get_role_mapping.cache_clear()
    get_service.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()


def login_as(client, subject: str) -> None:
    """Full Authorization-Code-flow login as the given test subject —
    real HTTP requests against the real `/auth/login`/`/auth/callback`
    routes (never a shortcut that directly injects a session), so every
    authorization test exercises the genuine end-to-end path."""
    resp = client.get("/api/v1/auth/login", follow_redirects=False)
    location = resp.headers["location"]
    query = parse_qs(urlparse(location).query)
    state = query["state"][0]
    client.auth_runtime.token_options["nonce"] = query["nonce"][0]
    client.auth_runtime.token_options["subject"] = subject

    callback = client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    assert callback.status_code == 302, callback.text
