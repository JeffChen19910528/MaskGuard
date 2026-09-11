"""Phase 10.5: fixtures for rate-limit tests. Reuses Phase 10.3's mock-OIDC
+ role-mapping machinery (`tests/api/authorization/conftest.py`) directly —
same pattern Phase 10.4's audit tests already established
(`tests/api/audit/conftest.py`).
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

#: Every test-local default is small and deterministic — production values
#: would make burst/bypass tests slow and flaky (§112: "tests must be able
#: to configure small limits... do not use production values for all
#: tests"). `tests/api/ratelimit/test_rate_limit_production_config.py`
#: covers realistic production-sized values separately (§113).
_DEFAULT_RL_ENV = {
    "RATE_LIMIT_ENABLED": "true",
    "RATE_LIMIT_AUTH_CAPACITY": "3", "RATE_LIMIT_AUTH_WINDOW_SECONDS": "10",
    "RATE_LIMIT_READ_CAPACITY": "3", "RATE_LIMIT_READ_WINDOW_SECONDS": "10",
    "RATE_LIMIT_IMAGE_ANALYZE_CAPACITY": "3", "RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS": "10",
    "RATE_LIMIT_IMAGE_REDACT_CAPACITY": "3", "RATE_LIMIT_IMAGE_REDACT_WINDOW_SECONDS": "10",
    "RATE_LIMIT_IMAGE_VERIFY_CAPACITY": "3", "RATE_LIMIT_IMAGE_VERIFY_WINDOW_SECONDS": "10",
    "RATE_LIMIT_REVIEW_CAPACITY": "3", "RATE_LIMIT_REVIEW_WINDOW_SECONDS": "10",
    "RATE_LIMIT_AUDIT_QUERY_CAPACITY": "3", "RATE_LIMIT_AUDIT_QUERY_WINDOW_SECONDS": "10",
    "RATE_LIMIT_CLIENT_MULTIPLIER": "3",
    "RATE_LIMIT_MAX_KEYS": "1000",
    "RATE_LIMIT_CLEANUP_INTERVAL_SECONDS": "60",
}


def _clear_caches() -> None:
    get_auth_settings.cache_clear()
    get_role_mapping.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()
    get_service.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_lru_caches():
    """Several tests in this package call `build_client(...)` directly
    (not via the `client` fixture below) to pass per-test env overrides —
    `monkeypatch` reverts the env vars themselves at teardown, but the
    `lru_cache`d settings/limiter singletons are NOT env-var-aware and
    would otherwise leak this module's small test capacities (and
    OIDC/AUDIT settings) into whichever test runs next, in ANY test
    module — proven the hard way while writing this phase (see
    docs/rate-limit-implementation.md §20 "Testing"). Autouse: applies to
    every test in this directory regardless of which fixture it uses."""
    _clear_caches()
    yield
    _clear_caches()


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


def build_client(monkeypatch, tmp_path, provider, **env_overrides) -> TestClient:
    """Not a fixture itself — tests call this directly (after their own
    `monkeypatch`/`tmp_path`/`provider` fixtures are injected) so each test
    can override exactly the env vars it needs (§112)."""
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

    env = dict(_DEFAULT_RL_ENV)
    env.update(env_overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    _clear_caches()

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
    test_client = TestClient(app, raise_server_exceptions=False)
    test_client.__enter__()
    test_client.auth_runtime = runtime  # type: ignore[attr-defined]
    return test_client


@pytest.fixture()
def client(monkeypatch, tmp_path, provider):
    test_client = build_client(monkeypatch, tmp_path, provider)
    yield test_client
    test_client.__exit__(None, None, None)
    _clear_caches()
