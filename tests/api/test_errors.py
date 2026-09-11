"""Unified error response shape (§17) — no route here needs Tesseract; the
500 path is reached by making a validated request fail INSIDE the service
layer (a legitimate way to test error-handling infrastructure, not the same
thing as monkey-patching Core to fake a SUCCESSFUL result)."""
from __future__ import annotations

import io

from PIL import Image

from maskguard.api.dependencies import get_service


def _valid_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_invalid_image_error_has_unified_shape(client):
    r = client.post("/api/v1/analyze", files={"file": ("upload.txt", b"not an image", "text/plain")})
    body = r.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "request_id"}
    assert body["error"]["request_id"]


def test_unexpected_internal_error_returns_500_without_traceback(client, monkeypatch):
    class _BoomService:
        ocr_engine_available = True

        def analyze(self, *a, **k):
            raise RuntimeError("boom: something deep inside blew up at /some/internal/path.py:123")

    client.app.dependency_overrides[get_service] = lambda: _BoomService()
    try:
        r = client.post("/api/v1/analyze", files={"file": ("upload.png", _valid_png_bytes(), "image/png")})
        assert r.status_code == 500
        body = r.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"
        # The client-facing message must never include the exception text,
        # a file path, or a traceback fragment (§17).
        body_text = str(body).lower()
        for forbidden in ("boom", "runtimeerror", "traceback", ".py:", "/some/internal/"):
            assert forbidden not in body_text
    finally:
        client.app.dependency_overrides.clear()


def test_validation_error_on_missing_file_field_is_422(client):
    r = client.post("/api/v1/analyze", data={})  # no `file` part at all
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_route_is_404_not_traceback(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert "traceback" not in r.text.lower()
