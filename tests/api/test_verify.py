"""POST /api/v1/verify — calls `WholeImageSanityScanner` (Skill.md Phase
6.1 P0-2), not `VerificationEngine` (see service.py for why). Real
Tesseract, real Core."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("ocr_env")


def test_verify_reports_dirty_on_raw_unredacted_image(client, dataset_image):
    data = dataset_image("multiple_sensitive_values.png")
    r = client.post("/api/v1/verify", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["clean"] is False
    assert "TaiwanID" in body["found_critical_types"]


def test_verify_reports_clean_on_a_blank_image(client):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 100), (255, 255, 255)).save(buf, format="PNG")
    r = client.post("/api/v1/verify", files={"file": ("blank.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert body["clean"] is True
    assert body["found_types"] == []
    assert body["found_critical_types"] == []


def test_verify_response_shape(client, dataset_image):
    data = dataset_image("Email_clean.png")
    r = client.post("/api/v1/verify", files={"file": ("upload.png", data, "image/png")})
    body = r.json()
    assert set(body.keys()) == {"clean", "found_types", "found_critical_types"}
    assert isinstance(body["found_types"], list)
    assert isinstance(body["found_critical_types"], list)


def test_verify_does_not_require_a_prior_analyze_call(client, dataset_image):
    """Standalone: no detection context is passed in, matching the sanity
    scanner's real contract (fresh OCR + fresh detection every call)."""
    data = dataset_image("TaiwanID_clean.png")
    r = client.post("/api/v1/verify", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    assert r.json()["clean"] is False
