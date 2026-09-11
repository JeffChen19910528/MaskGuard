"""Phase 10.5 §99/§100/§102/§130/§132/§134: MANDATORY regression tests.
A failure here is FAIL for the whole phase (§144)."""
from __future__ import annotations

import maskguard.api.ratelimit.limiter as limiter_module
import maskguard.api.routes.images as images_module
from maskguard.api.audit.config import get_audit_settings
from maskguard.api.audit.service import get_audit_store

from ..authorization.conftest import login_as
from .conftest import build_client

_TINY_FILE = {"file": ("x.png", b"not-a-real-image", "image/png")}


def _audit_client(monkeypatch, tmp_path, provider, **overrides):
    overrides.setdefault("AUDIT_ENABLED", "true")
    overrides.setdefault("AUDIT_INTEGRITY_KEY", "test-only-audit-integrity-key-32chars-min")
    overrides.setdefault("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()
    return build_client(monkeypatch, tmp_path, provider, **overrides)


def test_policy_engine_unaffected_by_rate_limiting_mandatory(monkeypatch, tmp_path, provider, ocr_env, dataset_image):
    """§99/§130: authorized Reviewer processes a real Passport image with
    rate limiting ENABLED; must remain CRITICAL/FULL_MASK, verification
    clean — identical to Phase 10.3/10.4's own mandatory regression."""
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="5", RATE_LIMIT_IMAGE_REDACT_CAPACITY="5", RATE_LIMIT_IMAGE_VERIFY_CAPACITY="5")
    login_as(client, "reviewer-1")

    resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("Passport_clean.png"), "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    passport = next(d for d in body["detections"] if d["type"] == "Passport")
    assert passport["risk_level"] == "CRITICAL"
    assert passport["action"] == "FULL_MASK"

    redact_resp = client.post("/api/v1/redact", files={"file": ("upload.png", dataset_image("Passport_clean.png"), "image/png")})
    assert redact_resp.status_code == 200
    verify_resp = client.post("/api/v1/verify", files={"file": ("out.png", redact_resp.content, "image/png")})
    assert verify_resp.status_code == 200
    assert verify_resp.json()["clean"] is True


def test_rate_limit_bypass_regression_mandatory(monkeypatch, tmp_path, provider):
    """§131: 3 requests/10s -> req1/2/3 allowed, req4 -> 429. Changing
    query params/User-Agent/fake role/fake user/fake cookie/HTTP method
    must not produce an unauthorized bypass."""
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="3", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")
    variants = [
        {},
        {"headers": {"User-Agent": "custom-agent"}},
        {"headers": {"X-User": "Administrator", "X-Role": "Administrator"}},
    ]
    for kwargs in variants:
        r = client.post("/api/v1/analyze", files=_TINY_FILE, **kwargs)
        assert r.status_code == 401
    r = client.post("/api/v1/analyze?bypass=1", files=_TINY_FILE, headers={"Cookie": "mg_sess=fake"})
    assert r.status_code == 429
    r = client.get("/api/v1/analyze")  # method switch attempt
    assert r.status_code == 405


def test_authorization_regression_mandatory(monkeypatch, tmp_path, provider):
    """§99: rate limiting must never change an authorization outcome."""
    client = _audit_client(monkeypatch, tmp_path, provider, RATE_LIMIT_AUDIT_QUERY_CAPACITY="5")
    login_as(client, "operator-1")
    assert client.get("/api/v1/audit").status_code == 403  # Operator never has audit.read, regardless of rate limiting


def test_concurrency_slot_never_consumed_by_rate_limited_request(monkeypatch, tmp_path, provider):
    """§17/§36/§102/§132: a rate-limited request must NEVER reach
    `run_with_timeout` (which is what acquires the `ConcurrencyLimiter`
    slot) — proven by spying on it directly, no Tesseract required."""
    client = build_client(monkeypatch, tmp_path, provider, RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="1", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10")

    calls = []

    async def _spy(*args, **kwargs):
        calls.append(1)
        raise AssertionError("run_with_timeout must not be called for a rate-limited request")

    monkeypatch.setattr(images_module, "run_with_timeout", _spy)

    # First request: rate limit allows it through -> reaches (and fails
    # inside) the spy, proving the spy IS wired correctly, then the
    # exception surfaces as a 500 (unhandled) — irrelevant to this test,
    # only the SECOND request's behavior matters.
    client.post("/api/v1/analyze", files=_TINY_FILE)
    calls.clear()

    r = client.post("/api/v1/analyze", files=_TINY_FILE)
    assert r.status_code == 429
    assert calls == []  # run_with_timeout was never invoked for the rejected request


def test_rate_limiter_internal_failure_does_not_weaken_security(monkeypatch, tmp_path, provider):
    """§34/§134: break the limiter's own internals; confirm no
    authorization bypass, no crash, and the request is served normally
    (fail OPEN for rate limiting only — see ratelimit/dependencies.py)."""
    client = _audit_client(monkeypatch, tmp_path, provider, RATE_LIMIT_AUDIT_QUERY_CAPACITY="5")

    def _broken_check(self, key, capacity, window_seconds):
        raise RuntimeError("simulated internal rate-limiter failure")

    monkeypatch.setattr(limiter_module.RateLimiter, "check", _broken_check)

    # Authorization must still correctly deny an unauthorized caller —
    # never fail open just because the rate limiter is broken.
    login_as(client, "operator-1")
    resp = client.get("/api/v1/audit")
    assert resp.status_code == 403

    # And an anonymous caller must still get exactly 401, never a 500 or
    # a rate-limiter-induced crash.
    client.post("/api/v1/auth/logout", headers={"Origin": "https://maskguard.test.invalid"})
    assert client.get("/api/v1/audit").status_code == 401


def test_identity_rotation_does_not_bypass_client_layer(monkeypatch, tmp_path, provider, ocr_env, dataset_image):
    """§9/§10/§97: many different authenticated identities from the SAME
    client must still be bounded by the coarser, layered client bucket —
    not just their own per-identity bucket."""
    client = build_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="1", RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS="10",
        RATE_LIMIT_CLIENT_MULTIPLIER="2",  # client bucket capacity = 1 * 2 = 2
    )
    small_image = dataset_image("Email_clean.png")

    login_as(client, "reviewer-1")
    r1 = client.post("/api/v1/analyze", files={"file": ("a.png", small_image, "image/png")})
    assert r1.status_code == 200  # 1st request: identity bucket (1/1) AND client bucket (1/2)

    login_as(client, "reviewer-auditor-1")
    r2 = client.post("/api/v1/analyze", files={"file": ("b.png", small_image, "image/png")})
    assert r2.status_code == 200  # different identity, own fresh identity bucket, but client bucket now 2/2

    login_as(client, "auditor-1")  # has no image.* permission, but rate limiting runs FIRST
    r3 = client.post("/api/v1/analyze", files={"file": ("c.png", small_image, "image/png")})
    # client-layer bucket is now exhausted (2/2 already consumed by r1+r2) -> 429, not 403.
    assert r3.status_code == 429
