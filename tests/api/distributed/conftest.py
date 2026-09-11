"""Phase 10.6: fixtures for MULTI-INSTANCE simulation tests. Builds TWO
independently-wired "nodes" (`node_a`, `node_b`) — each its OWN
`AuthRuntime` (own Redis session/transaction stores, own `redis.Redis`
connection) and its OWN `MaskGuardService` (own Redis replay store, own
connection) — sharing only the SAME real Redis server (`redis_container`,
`tests/redis_env.py`), the SAME namespace, and the SAME review-token HMAC
secret (mandatory for cross-node token verification, §66/§26). This is
what makes "cross-node" tests genuine: the two nodes interoperate
entirely through shared Redis state, never through shared Python objects
— they use SEPARATE TCP connections, separate `AuthRuntime`/service
instances, exactly like two separate OS processes would.

Rate-limit checks are the one exception, disclosed here rather than
hidden: `require_rate_limit`'s internal Redis-limiter singleton is
process-`lru_cache`d and not wired through `dependency_overrides` (it
isn't a route-level `Depends` target), so both TestClient apps in THIS
test process necessarily share that one Python object. This does not
weaken the rate-limit tests below — they still exercise the full
route -> dependency -> real-Redis path — but true cross-PROCESS
independence for the rate limiter is proven separately by
`tests/test_redis_rate_limiter.py::test_cross_node_shared_limit_not_per_node`
(two genuinely independent objects/connections) and by the live Docker
multi-instance validation (real separate containers).
"""
from __future__ import annotations

import time
import uuid

import httpx
import pytest
import redis as redis_lib
from fastapi.testclient import TestClient

from maskguard.api.app import create_app
from maskguard.api.audit.config import get_audit_settings
from maskguard.api.audit.service import get_audit_store
from maskguard.api.auth.config import get_auth_settings
from maskguard.api.auth.dependencies import AuthRuntime, _DiscoveryCache, get_auth_runtime
from maskguard.api.auth.discovery import OidcDiscoveryDocument
from maskguard.api.auth.session import RedisPendingTransactionStore, RedisSessionStore
from maskguard.api.authorization.role_config import get_role_mapping
from maskguard.api.config import get_settings
from maskguard.api.dependencies import get_service
from maskguard.api.ratelimit.config import get_rate_limit_settings
from maskguard.api.ratelimit.dependencies import _get_redis_rate_limiter, get_rate_limiter
from maskguard.api.redisstate.client import get_redis_client
from maskguard.api.redisstate.config import get_redis_settings
from maskguard.api.review_token import RedisReplayStore
from maskguard.api.service import MaskGuardService

from ..auth.mock_provider import FakeKeyProvider, MockOidcProvider
from ..authorization.conftest import CLIENT_ID, ISSUER, REDIRECT_URI, _write_role_mapping_file

REVIEW_SECRET = "test-only-shared-review-secret-32-bytes-minimum"


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_auth_settings.cache_clear()
    get_role_mapping.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()
    _get_redis_rate_limiter.cache_clear()
    get_redis_settings.cache_clear()
    get_redis_client.cache_clear()
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()
    get_service.cache_clear()


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


def _build_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options, env_overrides):
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
    monkeypatch.setenv("MASKGUARD_REVIEW_TOKEN_SECRET", REVIEW_SECRET)
    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("REDIS_NAMESPACE", namespace)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, value)

    _clear_caches()

    auth_settings = get_auth_settings()
    session_client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    runtime = AuthRuntime(
        settings=auth_settings,
        session_store=RedisSessionStore(session_client, namespace),
        transaction_store=RedisPendingTransactionStore(session_client, namespace),
        http_client=httpx.AsyncClient(transport=_make_transport(provider, token_options)),
    )
    doc = OidcDiscoveryDocument(**provider.discovery_document())
    runtime._discovery_cache = _DiscoveryCache(document=doc, key_provider=FakeKeyProvider(provider), fetched_at=time.time())
    runtime.token_options = token_options  # type: ignore[attr-defined]

    replay_client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    service = MaskGuardService(
        review_token_ttl_seconds=600, max_concurrent_jobs=4,
        review_token_secret=REVIEW_SECRET, replay_store=RedisReplayStore(replay_client, namespace),
    )

    app = create_app()
    app.dependency_overrides[get_auth_runtime] = lambda: runtime
    app.dependency_overrides[get_service] = lambda: service
    client = TestClient(app, raise_server_exceptions=False)
    client.__enter__()
    client.auth_runtime = runtime  # type: ignore[attr-defined]
    return client


@pytest.fixture()
def two_nodes(monkeypatch, provider, redis_url):
    """Yields `(node_a, node_b, token_options)` — two independent
    TestClient "nodes" sharing one real Redis namespace and the same
    OIDC mock provider/role mapping. `token_options` is the ONE shared
    dict both nodes' mock transports read `subject`/`nonce` from, so
    `login_as()` below can drive login on EITHER node."""
    import tempfile
    from pathlib import Path

    tmp_dir = Path(tempfile.mkdtemp())
    role_mapping_path = _write_role_mapping_file(tmp_dir)
    namespace = f"maskguard:test-{uuid.uuid4().hex[:10]}:"
    token_options: dict = {}
    env_overrides = {
        "RATE_LIMIT_IMAGE_ANALYZE_CAPACITY": "3", "RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS": "10",
        "RATE_LIMIT_REVIEW_CAPACITY": "3", "RATE_LIMIT_REVIEW_WINDOW_SECONDS": "10",
        "RATE_LIMIT_AUDIT_QUERY_CAPACITY": "5", "RATE_LIMIT_AUDIT_QUERY_WINDOW_SECONDS": "10",
    }
    node_a = _build_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options, env_overrides)
    node_b = _build_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options, env_overrides)
    try:
        yield node_a, node_b, token_options
    finally:
        node_a.__exit__(None, None, None)
        node_b.__exit__(None, None, None)
        _clear_caches()


def login_as(client, token_options: dict, subject: str) -> None:
    """Same shape as `tests/api/authorization/conftest.py::login_as` —
    real HTTP against the real `/auth/login`/`/auth/callback` routes on
    the GIVEN node."""
    from urllib.parse import parse_qs, urlparse

    resp = client.get("/api/v1/auth/login", follow_redirects=False)
    location = resp.headers["location"]
    query = parse_qs(urlparse(location).query)
    state = query["state"][0]
    token_options["nonce"] = query["nonce"][0]
    token_options["subject"] = subject

    callback = client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    assert callback.status_code == 302, callback.text


def cross_node_login(login_client, callback_client, token_options: dict, subject: str):
    """Login initiated on ONE node, callback completed on a DIFFERENT
    node — simulates a load balancer round-robining the two requests of
    a single login flow (§60/§116-117: no sticky sessions). Manually
    copies the `mg_txn` cookie between the two TestClient cookie jars,
    exactly what a real browser would do (send the same cookie
    regardless of which backend node answers)."""
    from urllib.parse import parse_qs, urlparse

    resp = login_client.get("/api/v1/auth/login", follow_redirects=False)
    location = resp.headers["location"]
    query = parse_qs(urlparse(location).query)
    state = query["state"][0]
    token_options["nonce"] = query["nonce"][0]
    token_options["subject"] = subject

    txn_cookie = login_client.cookies.get("mg_txn")
    callback_client.cookies.set("mg_txn", txn_cookie)
    callback = callback_client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    assert callback.status_code == 302, callback.text
    return callback
