"""Phase 10.6 §18/§30/§41/§92/§93/§94/§95/§96/§145/§182/§183: Redis
outage / failure-matrix attack tests. Breaks the ACTUAL Redis connection
(points at an unreachable host) rather than mocking — proves the real
client's timeout/error path, not an idealized one.
"""
from __future__ import annotations

from .conftest import _build_node, login_as

_TINY_FILE = {"file": ("x.png", b"not-a-real-image", "image/png")}
_UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/0"  # nothing listens on port 1 -> connection refused, bounded by our own short timeouts


def _broken_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options):
    """A node pointed at an UNREACHABLE Redis — simulates §18/§92 "Redis
    unavailable" for every one of its own requests."""
    node = _build_node(
        monkeypatch, provider, _UNREACHABLE_REDIS_URL, namespace, role_mapping_path, token_options,
        {
            "REDIS_SOCKET_TIMEOUT_SECONDS": "1", "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS": "1",
            "RATE_LIMIT_IMAGE_ANALYZE_CAPACITY": "3", "RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS": "10",
        },
    )
    return node


def test_redis_outage_read_endpoint_fails_closed_even_without_cookie(monkeypatch, provider, redis_url, tmp_path):
    """§18/§41/§95: `/auth/me` is ALSO rate-limit-protected (READ class,
    Phase 10.5) — under a Redis outage, the rate-limit dependency itself
    fails closed BEFORE the session lookup even runs, so a 503 is
    correct here too, regardless of whether a cookie is present. This
    confirms the fail-closed posture is consistent end-to-end across
    every dependency layered on the route, not just the one being
    exercised directly."""
    from ..authorization.conftest import _write_role_mapping_file

    role_mapping_path = _write_role_mapping_file(tmp_path)
    token_options: dict = {}
    namespace = "maskguard:test-outage:"
    node = _broken_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options)
    try:
        resp = node.get("/api/v1/auth/me")
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    finally:
        node.__exit__(None, None, None)


def test_redis_outage_with_cookie_present_returns_503_not_authenticated(monkeypatch, provider, redis_url, tmp_path):
    """§18/§95/§97: a session cookie IS present (so Redis must actually
    be consulted) while Redis is unreachable -> 503, NEVER 200
    authenticated, NEVER silently treated as anonymous-then-401."""
    from ..authorization.conftest import _write_role_mapping_file

    role_mapping_path = _write_role_mapping_file(tmp_path)
    token_options: dict = {}
    namespace = "maskguard:test-outage2:"
    node = _broken_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options)
    try:
        node.cookies.set("mg_sess", "some-opaque-cookie-value")
        resp = node.get("/api/v1/auth/me")
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        # §98: no hostname/connection detail leaked.
        assert "127.0.0.1" not in resp.text
        assert "redis" not in resp.text.lower()
    finally:
        node.__exit__(None, None, None)


def test_redis_outage_authorization_fails_safe_not_open(monkeypatch, provider, redis_url, tmp_path):
    """§18/§95: FAIL condition #4 — a protected endpoint under Redis
    outage never returns 200 for an unverifiable identity."""
    from ..authorization.conftest import _write_role_mapping_file

    role_mapping_path = _write_role_mapping_file(tmp_path)
    token_options: dict = {}
    namespace = "maskguard:test-outage3:"
    node = _broken_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options)
    try:
        node.cookies.set("mg_sess", "some-opaque-cookie-value")
        resp = node.post("/api/v1/analyze", files=_TINY_FILE)
        # Rate limiting itself would ALSO fail closed (509 below covers
        # that path specifically) — either way, the response must never
        # be 200 (Core executed) under a broken identity/rate dependency.
        assert resp.status_code in (503,)
    finally:
        node.__exit__(None, None, None)


def test_redis_outage_rate_limit_fails_closed_not_unlimited(monkeypatch, provider, redis_url, tmp_path):
    """§41/§42/§96: FAIL condition #5 territory — rate limiting under
    Redis outage must reject the protected operation, never silently
    become unlimited, and NEVER fall back to local in-memory counting."""
    from ..authorization.conftest import _write_role_mapping_file

    role_mapping_path = _write_role_mapping_file(tmp_path)
    token_options: dict = {}
    namespace = "maskguard:test-outage4:"
    node = _broken_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options)
    try:
        # Anonymous request: rate limiting runs BEFORE authorization, so
        # a broken Redis rate limiter surfaces its OWN 503 first.
        resp = node.post("/api/v1/analyze", files=_TINY_FILE)
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    finally:
        node.__exit__(None, None, None)


def test_redis_outage_no_process_crash(monkeypatch, provider, redis_url, tmp_path):
    """§34/§92: repeated requests against a broken Redis must not crash
    the process — every one gets a clean, typed error response."""
    from ..authorization.conftest import _write_role_mapping_file

    role_mapping_path = _write_role_mapping_file(tmp_path)
    token_options: dict = {}
    namespace = "maskguard:test-outage5:"
    node = _broken_node(monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options)
    try:
        for _ in range(5):
            resp = node.post("/api/v1/analyze", files=_TINY_FILE)
            assert resp.status_code == 503
            assert "error" in resp.json()
    finally:
        node.__exit__(None, None, None)


def test_healthy_node_unaffected_by_others_local_redis_client_break(two_nodes, monkeypatch):
    """§183: partial node failure — Node A's own Redis CLIENT object is
    monkeypatched to always raise (simulating a locally-broken client,
    distinct from a real network outage), Node B (genuinely healthy,
    separate connection) continues operating normally."""
    node_a, node_b, token_options = two_nodes
    login_as(node_b, token_options, "operator-1")

    import redis as redis_lib

    def _always_raise(*args, **kwargs):
        raise redis_lib.exceptions.ConnectionError("simulated local failure on node A only")

    monkeypatch.setattr(node_a.auth_runtime.session_store._client, "get", _always_raise)

    node_a.cookies.set("mg_sess", "whatever")
    resp_a = node_a.get("/api/v1/auth/me")
    assert resp_a.status_code == 503  # Node A fails safely

    resp_b = node_b.get("/api/v1/auth/me")
    assert resp_b.status_code == 200
    assert resp_b.json()["authenticated"] is True  # Node B, genuinely healthy, unaffected
