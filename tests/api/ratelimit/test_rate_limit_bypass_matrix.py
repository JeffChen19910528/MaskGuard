"""Phase 10.5 §39-46/§92/§97: bypass-matrix tests. Rate limiting runs
BEFORE authorization (§2/§23) — every one of these requests is anonymous
and would eventually be denied 401, but the rate-limit dependency still
consumes a token first (§98: "unauthorized request... does not bypass
rate limiting"), so exhausting the bucket needs no Tesseract/valid image
at all: the file bytes never get validated.
"""
from __future__ import annotations

from .conftest import build_client

_TINY_FILE = {"file": ("x.png", b"not-a-real-image", "image/png")}


def _exhaust_analyze(client, n: int = 3):
    for _ in range(n):
        r = client.post("/api/v1/analyze", files=_TINY_FILE)
        assert r.status_code == 401  # rate limit allowed it through; auth denied it
    return client


def test_endpoint_switching_does_not_bypass(monkeypatch, tmp_path, provider):
    # §39/§97: analyze exhausted must not free up capacity on redact/verify
    # — each class has its OWN bucket, but ALSO each is independently
    # rate limited (not "switching resets the counter").
    client = build_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10",
        RATE_LIMIT_IMAGE_REDACT_CAPACITY="3", RATE_LIMIT_IMAGE_REDACT_WINDOW_SECONDS="10",
    )
    _exhaust_analyze(client)
    r = client.post("/api/v1/analyze", files=_TINY_FILE)
    assert r.status_code == 429
    # redact has its OWN, still-fresh budget:
    r2 = client.post("/api/v1/redact", files=_TINY_FILE)
    assert r2.status_code == 401  # not 429 — redact's bucket is independent


def test_http_method_switching_never_reaches_core(monkeypatch, tmp_path, provider):
    # §40: unsupported methods are rejected by routing itself (405),
    # never a hidden bypass around rate limiting.
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="1")
    for method in ("get", "put", "patch", "delete"):
        r = getattr(client, method)("/api/v1/analyze")
        assert r.status_code == 405


def test_query_parameter_variation_does_not_create_new_buckets(monkeypatch, tmp_path, provider):
    # §42: /analyze?x=1 and /analyze?x=2 must share ONE bucket.
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")
    for i in range(3):
        r = client.post(f"/api/v1/analyze?x={i}", files=_TINY_FILE)
        assert r.status_code == 401
    r = client.post("/api/v1/analyze?x=999", files=_TINY_FILE)
    assert r.status_code == 429


def test_trailing_slash_does_not_bypass(monkeypatch, tmp_path, provider):
    # §41: FastAPI's own canonical routing normalizes the trailing slash
    # (redirect to the same route) — no separate bucket is created.
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="2", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")
    for _ in range(2):
        r = client.post("/api/v1/analyze/", files=_TINY_FILE, follow_redirects=True)
        assert r.status_code in (401, 404)  # either denied or not-found — never a fresh bucket
    r = client.post("/api/v1/analyze", files=_TINY_FILE)
    assert r.status_code == 429


def test_fake_identity_headers_do_not_change_key(monkeypatch, tmp_path, provider):
    # §6/§10/§45/§97: X-User/X-Role/X-Permission/fake cookies are NEVER
    # trusted as identity — sending them (or not) must land in the SAME
    # anonymous bucket.
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")
    spoof_headers = [
        {"X-User": "Administrator"},
        {"X-Role": "Administrator", "X-Permission": "audit.read"},
        {"Cookie": "mg_sess=totally-fake-session-value"},
    ]
    for headers in spoof_headers:
        r = client.post("/api/v1/analyze", files=_TINY_FILE, headers=headers)
        assert r.status_code == 401  # never 200/403 from a "recognized" fake identity
    # bucket capacity (3) is now exhausted regardless of the headers sent:
    r = client.post("/api/v1/analyze", files=_TINY_FILE)
    assert r.status_code == 429


def test_user_agent_rotation_does_not_bypass(monkeypatch, tmp_path, provider):
    # §44/§97
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")
    for i in range(3):
        r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"User-Agent": f"attacker-agent-{i}"})
        assert r.status_code == 401
    r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"User-Agent": "yet-another-one"})
    assert r.status_code == 429


def test_host_header_rotation_does_not_bypass(monkeypatch, tmp_path, provider):
    # §43/§97
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")
    for i in range(3):
        r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"Host": f"attacker-{i}.example"})
        assert r.status_code == 401
    r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"Host": "another-attacker.example"})
    assert r.status_code == 429


def test_forwarded_for_spoofing_ignored_when_proxy_not_trusted(monkeypatch, tmp_path, provider):
    # §6/§8/§43: X-Forwarded-For is never read at all in this phase
    # (identity.py) — RATE_LIMIT_TRUST_PROXY_HEADERS defaults to False.
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")
    for i in range(3):
        r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"X-Forwarded-For": f"1.2.3.{i}"})
        assert r.status_code == 401
    r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"X-Forwarded-For": "9.9.9.9"})
    assert r.status_code == 429  # still the SAME (direct-peer) bucket — spoofed XFF changed nothing


def test_x_real_ip_only_trusted_when_configured(monkeypatch, tmp_path, provider):
    # §8/§118: sending X-Real-IP has NO effect unless
    # RATE_LIMIT_TRUST_PROXY_HEADERS=true is explicitly configured — the
    # default (false, direct/dev/test topology).
    client = build_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10",
        RATE_LIMIT_TRUST_PROXY_HEADERS="false",
    )
    for i in range(3):
        r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"X-Real-IP": f"10.0.0.{i}"})
        assert r.status_code == 401
    r = client.post("/api/v1/analyze", files=_TINY_FILE, headers={"X-Real-IP": "10.0.0.99"})
    assert r.status_code == 429
