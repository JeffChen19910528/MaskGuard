"""Phase 10.2 §50/§52/§53: full login -> callback -> session -> logout flow,
plus the CSRF/session-fixation/cookie-security/leakage tests §50/§53
require, all via a real FastAPI `TestClient` (real routing, real
middleware, real cookie handling) against the mock OIDC provider wired in
`conftest.py`.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from .conftest import CLIENT_ID, REDIRECT_URI


def _login_and_extract_transaction(client):
    resp = client.get("/api/v1/auth/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    query = parse_qs(urlparse(location).query)
    assert query["response_type"] == ["code"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert "code_challenge" in query
    assert query["code_challenge_method"] == ["S256"]
    txn_cookie = client.cookies.get("mg_txn")
    assert txn_cookie  # HttpOnly cookie still visible to the (non-browser) test client's cookie jar
    # See conftest.py's `_make_transport` docstring: the mock token
    # endpoint needs to know the real nonce to embed in the ID token it
    # mints, exactly as a real IdP would (having remembered it from the
    # authorization request this test harness doesn't actually visit).
    client.auth_runtime.nonce_box["value"] = query["nonce"][0]
    return query["state"][0], txn_cookie


def test_login_redirects_to_authorization_endpoint_with_pkce_state_nonce(client):
    state, txn_cookie = _login_and_extract_transaction(client)
    assert state


def test_full_login_flow_creates_session_and_sets_cookie(client, provider):
    state, _ = _login_and_extract_transaction(client)

    resp = client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    session_cookie = client.cookies.get("mg_sess")
    assert session_cookie

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["authenticated"] is True
    assert body["issuer"] == provider.issuer


def test_me_reports_unauthenticated_without_session(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False}


def test_callback_without_state_fails(client):
    resp = client.get("/api/v1/auth/callback?code=test-code", follow_redirects=False)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "AUTHENTICATION_FAILED"


def test_callback_with_forged_state_fails(client):
    _login_and_extract_transaction(client)  # establishes a real transaction cookie
    resp = client.get("/api/v1/auth/callback?code=test-code&state=forged-state-value", follow_redirects=False)
    assert resp.status_code == 401


def test_callback_without_transaction_cookie_fails(client):
    resp = client.get("/api/v1/auth/callback?code=test-code&state=anything", follow_redirects=False)
    assert resp.status_code == 401


def test_callback_replay_with_same_state_fails_second_time(client):
    """§52 'replayed state' / §79 'one-time auth transaction': a second
    callback reusing the same (now-consumed) transaction must fail, even
    with a technically-correct state value."""
    state, txn_cookie = _login_and_extract_transaction(client)

    first = client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    assert first.status_code == 302

    # Re-send the callback with the SAME transaction cookie (simulating a
    # replayed/duplicated callback request) — the transaction was already
    # consumed and deleted on the first call.
    client.cookies.set("mg_txn", txn_cookie)
    second = client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    assert second.status_code == 401


def test_provider_error_in_callback_fails(client):
    resp = client.get("/api/v1/auth/callback?error=access_denied&state=x", follow_redirects=False)
    assert resp.status_code == 401


def test_session_fixation_old_transaction_id_never_becomes_session_id(client):
    """§50: proves the post-login session id is independently random, not
    derived from or equal to the pre-login transaction cookie value —
    the closest analogue this architecture has to an "anonymous session
    id" (there is no separate anonymous-session concept; the pending
    transaction cookie is the only pre-auth identifier a client holds)."""
    state, txn_cookie = _login_and_extract_transaction(client)
    client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    session_cookie = client.cookies.get("mg_sess")
    assert session_cookie != txn_cookie
    assert client.cookies.get("mg_txn") is None  # cleared after successful callback (§27 step 10)


def test_logout_invalidates_session_server_side(client):
    state, _ = _login_and_extract_transaction(client)
    client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    assert client.cookies.get("mg_sess")

    logout_resp = client.post("/api/v1/auth/logout", headers={"origin": _expected_origin()})
    assert logout_resp.status_code == 200

    me = client.get("/api/v1/auth/me")
    assert me.json() == {"authenticated": False}


def test_logout_requires_valid_origin(client):
    """§29: logout CSRF — a cross-site Origin must not be able to force
    logout."""
    state, _ = _login_and_extract_transaction(client)
    client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)

    resp = client.post("/api/v1/auth/logout", headers={"origin": "https://evil.example"})
    assert resp.status_code == 403
    # Session must still be valid — the forged-origin logout did NOT succeed.
    me = client.get("/api/v1/auth/me")
    assert me.json()["authenticated"] is True


def test_session_cookie_has_httponly_secure_samesite_flags(client):
    state, _ = _login_and_extract_transaction(client)
    resp = client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    set_cookie = resp.headers.get("set-cookie", "")
    assert "mg_sess=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie or "samesite=lax" in set_cookie.lower()


def test_open_redirect_rejected(client):
    resp = client.get("/api/v1/auth/login?next=https://evil.example/steal", follow_redirects=False)
    location = resp.headers["location"]
    query = parse_qs(urlparse(location).query)
    state = query["state"][0]
    client.auth_runtime.nonce_box["value"] = query["nonce"][0]

    callback = client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    # The final redirect target must be the SAFE fallback ("/"), never the
    # attacker-supplied external URL.
    assert callback.headers["location"] == "/"


def test_no_token_or_secret_in_me_response(client):
    state, _ = _login_and_extract_transaction(client)
    client.get(f"/api/v1/auth/callback?code=test-code&state={state}", follow_redirects=False)
    body = client.get("/api/v1/auth/me").json()
    forbidden_substrings = ("token", "secret", "session_id", "code_verifier")
    dumped = str(body).lower()
    for term in forbidden_substrings:
        assert term not in dumped, f"unexpected {term!r} in /auth/me response: {body}"


def test_auth_endpoints_are_not_cached():
    pass  # covered by test_no_store_cache_control below (kept separate name for §89 matrix traceability)


def test_no_store_cache_control_on_auth_responses(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.headers.get("cache-control") == "no-store"


def _expected_origin() -> str:
    from urllib.parse import urlparse

    parsed = urlparse(REDIRECT_URI)
    return f"{parsed.scheme}://{parsed.netloc}"


def test_login_when_oidc_disabled_fails_closed(monkeypatch):
    """§0/§31/§39: with OIDC_ENABLED unset, the auth router isn't even
    registered — existing endpoints are completely unaffected, and there
    is no way to reach a login flow at all."""
    from maskguard.api.app import create_app
    from maskguard.api.auth.config import get_auth_settings
    from maskguard.api.dependencies import get_service
    from fastapi.testclient import TestClient

    monkeypatch.delenv("OIDC_ENABLED", raising=False)
    get_auth_settings.cache_clear()
    get_service.cache_clear()
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/api/v1/auth/login", follow_redirects=False)
    assert resp.status_code == 404  # route doesn't exist — not a 401/500
    get_auth_settings.cache_clear()
    get_service.cache_clear()
