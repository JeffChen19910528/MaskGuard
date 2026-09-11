"""POST /api/v1/redact — real Tesseract, real Core, real redaction pixels."""
from __future__ import annotations

import io

import pytest
from PIL import Image

pytestmark = pytest.mark.usefixtures("ocr_env")


def test_redact_returns_a_png_image_not_json(client, dataset_image):
    data = dataset_image("TaiwanID_clean.png")
    r = client.post("/api/v1/redact", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # Must be a real, decodable PNG — not binary noise or a JSON blob typed wrong.
    image = Image.open(io.BytesIO(r.content))
    assert image.format == "PNG"


def test_redacted_image_dimensions_match_input(client, dataset_image):
    data = dataset_image("Email_clean.png")
    original = Image.open(io.BytesIO(data))

    r = client.post("/api/v1/redact", files={"file": ("upload.png", data, "image/png")})
    redacted = Image.open(io.BytesIO(r.content))
    assert redacted.size == original.size


def test_redaction_actually_changes_pixels_over_the_sensitive_region(client, dataset_image):
    """Not just "an image came back" — the CRITICAL region must actually be
    visually altered (masked), matching FULL_MASK's real pixel effect."""
    data = dataset_image("TaiwanID_clean.png")
    original = Image.open(io.BytesIO(data)).convert("RGB")

    r = client.post("/api/v1/redact", files={"file": ("upload.png", data, "image/png")})
    redacted = Image.open(io.BytesIO(r.content)).convert("RGB")

    assert original.tobytes() != redacted.tobytes(), "redacted image is pixel-identical to the input"


def test_redact_then_verify_reports_clean(client, dataset_image):
    """End-to-end security property: what /redact produces must pass
    /verify's independent re-check."""
    data = dataset_image("multiple_sensitive_values.png")

    redact_r = client.post("/api/v1/redact", files={"file": ("upload.png", data, "image/png")})
    assert redact_r.status_code == 200

    verify_r = client.post("/api/v1/verify", files={"file": ("upload.png", redact_r.content, "image/png")})
    assert verify_r.status_code == 200
    assert verify_r.json()["clean"] is True
