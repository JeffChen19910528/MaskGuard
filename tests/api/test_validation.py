"""Upload validation (§12) — none of these need Tesseract; every case is
rejected before Core ever sees the file."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from maskguard.api.config import ApiSettings, get_settings


@pytest.mark.parametrize("route", ["/api/v1/analyze", "/api/v1/redact", "/api/v1/verify"])
def test_rejects_non_image_file(client, route):
    r = client.post(route, files={"file": ("upload.txt", b"not an image at all", "text/plain")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "INVALID_IMAGE"


def test_rejects_empty_file(client):
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", b"", "image/png")})
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "INVALID_IMAGE"


def test_content_type_header_is_not_trusted(client):
    # Claims to be a PNG via Content-Type, but the bytes are plain text —
    # must still be rejected (§12: "Content-Type=image/png 不能代表實際就是 PNG").
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", b"just some text bytes", "image/png")})
    assert r.status_code == 415


def test_rejects_truncated_corrupt_image(client):
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (255, 255, 255)).save(buf, format="PNG")
    truncated = buf.getvalue()[:20]  # header only, no real pixel data
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", truncated, "image/png")})
    assert r.status_code == 415


def test_accepts_a_real_small_png_past_validation(client):
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), (255, 255, 255)).save(buf, format="PNG")
    r = client.post("/api/v1/verify", files={"file": ("upload.png", buf.getvalue(), "image/png")})
    # Reaches Core (verify doesn't need Tesseract's chi_tra to run on a
    # blank image, but DOES need the tesseract binary itself — if it's
    # genuinely missing this still proves validation passed by getting past
    # 415/413/422 into Core's own error path, so accept either outcome).
    assert r.status_code in (200, 500)


def test_file_too_large_is_rejected_before_full_decode(client, monkeypatch):
    tiny_limit = ApiSettings(max_upload_size_bytes=10)
    client.app.dependency_overrides[get_settings] = lambda: tiny_limit
    try:
        r = client.post("/api/v1/analyze", files={"file": ("upload.png", b"0" * 1000, "image/png")})
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "FILE_TOO_LARGE"
    finally:
        client.app.dependency_overrides.clear()


def test_image_dimensions_over_limit_are_rejected(client):
    tiny_dims = ApiSettings(max_image_width=10, max_image_height=10)
    client.app.dependency_overrides[get_settings] = lambda: tiny_dims
    try:
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), (255, 255, 255)).save(buf, format="PNG")
        r = client.post("/api/v1/analyze", files={"file": ("upload.png", buf.getvalue(), "image/png")})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "IMAGE_DIMENSIONS_INVALID"
    finally:
        client.app.dependency_overrides.clear()


def test_unsupported_format_is_rejected(client):
    buf = io.BytesIO()
    # GIF is a real, decodable image format Pillow supports — but it's
    # deliberately NOT in the adapter's allowlist (matches cli.py's
    # supported-suffix set), so this must be rejected as unsupported, not
    # silently accepted just because Pillow could decode it.
    Image.new("RGB", (20, 20), (255, 255, 255)).save(buf, format="GIF")
    r = client.post("/api/v1/analyze", files={"file": ("upload.gif", buf.getvalue(), "image/gif")})
    assert r.status_code == 415
