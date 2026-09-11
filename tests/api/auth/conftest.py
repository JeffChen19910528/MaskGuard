"""Phase 10.2 §54: shared fixtures for full-flow (TestClient-level) auth
tests. Wires a `MockOidcProvider` in via FastAPI's own `dependency_overrides`
mechanism (the standard, idiomatic way to substitute a dependency in
tests) — no monkeypatching of production internals, no real network
access, no real Internet IdP.
"""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from maskguard.api.app import create_app
from maskguard.api.auth.config import AuthSettings, get_auth_settings
from maskguard.api.auth.dependencies import AuthRuntime, get_auth_runtime
from maskguard.api.auth.session import InMemoryPendingTransactionStore, InMemorySessionStore
from maskguard.api.dependencies import get_service
from maskguard.api.ratelimit.config import get_rate_limit_settings
from maskguard.api.ratelimit.dependencies import get_rate_limiter

from .mock_provider import FakeKeyProvider, MockOidcProvider

ISSUER = "https://idp.test.invalid"
CLIENT_ID = "maskguard-client"
CLIENT_SECRET = "test-client-secret"
REDIRECT_URI = "https://maskguard.test.invalid/api/v1/auth/callback"


@pytest.fixture()
def provider() -> MockOidcProvider:
    return MockOidcProvider(issuer=ISSUER)


def _make_transport(provider: MockOidcProvider, nonce_box: dict, *, token_response_override: dict | None = None) -> httpx.MockTransport:
    """`nonce_box` simulates what a REAL IdP does naturally (remembers the
    nonce from the authorization request it served, then embeds it in the
    ID token it later mints) — this test harness skips actually visiting
    `authorization_endpoint` (TestClient never follows the redirect), so
    the test itself supplies the nonce it read from the login redirect's
    own query string via this shared box before triggering the callback."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=provider.discovery_document())
        if request.url.path == "/token":
            if token_response_override is not None:
                return httpx.Response(200, json=token_response_override)
            id_token = provider.issue_id_token(audience=CLIENT_ID, nonce=nonce_box.get("value", "test-nonce"))
            return httpx.Response(200, json={"id_token": id_token, "token_type": "Bearer"})
        return httpx.Response(404, json={"error": "not_found"})

    return httpx.MockTransport(handler)


@pytest.fixture()
def auth_settings() -> AuthSettings:
    return AuthSettings(
        oidc_enabled=True,
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scopes=("openid", "profile", "email"),
        clock_skew_seconds=120,
        cookie_secure_override=False,  # TestClient runs over plain http
        session_idle_timeout_seconds=1800,
        session_absolute_timeout_seconds=28800,
        max_sessions=100,
        max_pending_transactions=100,
        transaction_ttl_seconds=600,
    )


@pytest.fixture()
def auth_runtime(provider, auth_settings) -> AuthRuntime:
    nonce_box: dict = {}
    runtime = AuthRuntime(
        settings=auth_settings,
        session_store=InMemorySessionStore(max_sessions=auth_settings.max_sessions),
        transaction_store=InMemoryPendingTransactionStore(max_transactions=auth_settings.max_pending_transactions),
        http_client=httpx.AsyncClient(transport=_make_transport(provider, nonce_box)),
    )
    runtime.nonce_box = nonce_box  # type: ignore[attr-defined]  # test-only convenience, see _make_transport's docstring
    # Pre-seed the discovery cache with the fake key provider so the flow
    # never attempts a real JWKS network fetch (mock_provider.py's one
    # deliberate seam — see its module docstring).
    from maskguard.api.auth.dependencies import _DiscoveryCache
    from maskguard.api.auth.discovery import OidcDiscoveryDocument

    doc = OidcDiscoveryDocument(**provider.discovery_document())
    runtime._discovery_cache = _DiscoveryCache(document=doc, key_provider=FakeKeyProvider(provider), fetched_at=__import__("time").time())
    return runtime


@pytest.fixture()
def client(monkeypatch, auth_settings, auth_runtime):
    # `create_app()` reads OIDC settings directly (not via FastAPI
    # dependency injection) to decide whether to register the auth
    # router at all — env vars must match `auth_settings` for that
    # top-level gate, even though request-time behavior is driven by the
    # `get_auth_runtime` override below.
    monkeypatch.setenv("MASKGUARD_ENV", "development")
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("OIDC_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setenv("OIDC_CLOCK_SKEW_SECONDS", "120")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_SECONDS", "1800")
    monkeypatch.setenv("SESSION_ABSOLUTE_TIMEOUT_SECONDS", "28800")
    get_auth_settings.cache_clear()
    get_service.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()

    app = create_app()
    app.dependency_overrides[get_auth_runtime] = lambda: auth_runtime
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.auth_runtime = auth_runtime  # test-only convenience — see test_flow.py's login helper
        yield test_client
    app.dependency_overrides.clear()
    get_auth_settings.cache_clear()
    get_service.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()
