"""GET /api/v1/health — never requires Tesseract to construct/serve
(Pipeline/LocalOcrEngine construction doesn't probe the binary), and must
never run OCR or leak internals."""
from __future__ import annotations


def test_health_returns_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "api_version" in body
    assert "app_version" in body
    assert isinstance(body["ocr_engine_available"], bool)


def test_health_does_not_leak_filesystem_or_secrets(client):
    r = client.get("/api/v1/health")
    body_text = r.text.lower()
    for forbidden in ("c:\\", "/home/", "/users/", "site-packages", "traceback", "secret", "api_key"):
        assert forbidden not in body_text


def test_cors_default_is_restricted_not_wildcard(client):
    r = client.get("/api/v1/health", headers={"Origin": "http://example.com"})
    # Default CORS config has no allowed origins (§19) — Starlette's
    # CORSMiddleware simply omits Access-Control-Allow-Origin rather than
    # rejecting the request outright, so the absence of a wildcard/echoed
    # origin is what proves the restrictive default.
    allow_origin = r.headers.get("access-control-allow-origin")
    assert allow_origin != "*"
    assert allow_origin != "http://example.com"


def test_openapi_docs_available(client):
    r = client.get("/docs")
    assert r.status_code == 200

    r2 = client.get("/openapi.json")
    assert r2.status_code == 200
    spec_text = r2.text.lower()
    for forbidden in ("c:\\", "/home/", "site-packages", "password=", "secret_key="):
        assert forbidden not in spec_text
