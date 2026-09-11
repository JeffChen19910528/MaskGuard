"""Phase 10.5 §12/§13/§14/§15/§16/§93: authentication-endpoint rate
limiting. No Tesseract needed — none of these routes touch Core.
"""
from __future__ import annotations

from ..authorization.conftest import REDIRECT_URI
from .conftest import build_client

_ORIGIN_HEADERS = {"Origin": "https://maskguard.test.invalid"}
assert REDIRECT_URI.startswith(_ORIGIN_HEADERS["Origin"])


def test_login_burst_then_429(monkeypatch, tmp_path, provider):
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_AUTH_CAPACITY="3", RATE_LIMIT_AUTH_WINDOW_SECONDS="10")
    for _ in range(3):
        r = client.get("/api/v1/auth/login", follow_redirects=False)
        assert r.status_code == 302
    r = client.get("/api/v1/auth/login", follow_redirects=False)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) >= 1


def test_malformed_callback_still_counts_against_bucket(monkeypatch, tmp_path, provider):
    # §14: rate limiting is IP-keyed, never based on `state`/`code` — a
    # flood of malformed callbacks (never valid) is still bounded.
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_AUTH_CAPACITY="3", RATE_LIMIT_AUTH_WINDOW_SECONDS="10")
    for _ in range(3):
        r = client.get("/api/v1/auth/callback?code=bad&state=bad", follow_redirects=False)
        assert r.status_code == 401  # AuthenticationFailedError, never 429 yet
    r = client.get("/api/v1/auth/callback?code=bad&state=bad", follow_redirects=False)
    assert r.status_code == 429


def test_logout_rate_limited(monkeypatch, tmp_path, provider):
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_AUTH_CAPACITY="2", RATE_LIMIT_AUTH_WINDOW_SECONDS="10")
    for _ in range(2):
        r = client.post("/api/v1/auth/logout", headers=_ORIGIN_HEADERS)
        assert r.status_code == 200
    r = client.post("/api/v1/auth/logout", headers=_ORIGIN_HEADERS)
    assert r.status_code == 429


def test_auth_me_rate_limited_read_class(monkeypatch, tmp_path, provider):
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_READ_CAPACITY="3", RATE_LIMIT_READ_WINDOW_SECONDS="10")
    for _ in range(3):
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200
        assert r.json() == {"authenticated": False}
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 429


def test_auth_me_normal_browser_polling_not_broken_by_defaults(monkeypatch, tmp_path, provider):
    # §16/§58: the DEFAULT (not test-shrunk) READ policy must not make
    # ordinary browser startup unusable — a handful of calls succeed.
    client = build_client(monkeypatch, tmp_path, provider)  # defaults from _DEFAULT_RL_ENV: capacity=3/10s (still test-scale) is fine for THIS assertion
    for _ in range(3):
        assert client.get("/api/v1/auth/me").status_code == 200


def test_rate_limiting_disabled_is_a_complete_no_op(monkeypatch, tmp_path, provider):
    # §0/§56: opt-in — matching every other Phase 10.x control.
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_ENABLED="false", RATE_LIMIT_AUTH_CAPACITY="1")
    for _ in range(10):
        r = client.get("/api/v1/auth/login", follow_redirects=False)
        assert r.status_code == 302
        assert "X-RateLimit-Limit" not in r.headers


def test_retry_after_bounded_and_positive(monkeypatch, tmp_path, provider):
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_AUTH_CAPACITY="1", RATE_LIMIT_AUTH_WINDOW_SECONDS="5")
    client.get("/api/v1/auth/login", follow_redirects=False)
    r = client.get("/api/v1/auth/login", follow_redirects=False)
    assert r.status_code == 429
    retry_after = int(r.headers["Retry-After"])
    assert 1 <= retry_after <= 5


def test_429_body_never_leaks_internal_state(monkeypatch, tmp_path, provider):
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_AUTH_CAPACITY="1")
    client.get("/api/v1/auth/login", follow_redirects=False)
    r = client.get("/api/v1/auth/login", follow_redirects=False)
    body = r.text
    assert "testclient" not in body.lower()  # no raw client IP
    assert "bucket" not in body.lower() and "counter" not in body.lower()
    payload = r.json()
    assert set(payload["error"].keys()) == {"code", "message", "request_id"}
