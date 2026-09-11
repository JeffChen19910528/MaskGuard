"""POST /api/v1/analyze — real Tesseract, real MaskGuard Core, real Phase 6
dataset fixtures. No monkey-patching of Core (§26): every assertion here
depends on the actual OCR->Detection->Risk->Policy->Redaction->Verification
chain running for real."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("ocr_env")

_TYPE_FIXTURES = [
    ("Email_clean.png", "Email"),
    ("TaiwanID_clean.png", "TaiwanID"),
    ("CreditCard_clean.png", "CreditCard"),
    ("BankAccount_clean.png", "BankAccount"),
    ("Passport_clean.png", "Passport"),
    ("APIKey_clean.png", "SecretKeyValue"),
    ("Password_clean.png", "SecretKeyValue"),
    ("PhoneTW_clean.png", "Phone"),  # canonicalized (Phase 6.3) — never "PhoneTW"
]


@pytest.mark.parametrize("filename,expected_type", _TYPE_FIXTURES)
def test_analyze_finds_expected_type(client, dataset_image, filename, expected_type):
    data = dataset_image(filename)
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    body = r.json()
    found_types = {d["type"] for d in body["detections"]}
    assert expected_type in found_types, f"expected {expected_type} in {found_types}"


def test_analyze_response_matches_documented_shape(client, dataset_image):
    data = dataset_image("multiple_sensitive_values.png")
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    body = r.json()

    # Phase 8.3 adds `review_token` (top-level) and `detection_id` (per
    # detection) — see maskguard/api/schemas.py.
    assert set(body.keys()) == {
        "status", "needs_human_review", "blocked", "detections", "verification", "summary", "review_token",
    }
    assert isinstance(body["needs_human_review"], bool)
    assert isinstance(body["detections"], list) and body["detections"]
    assert isinstance(body["review_token"], str) and body["review_token"]

    detection = body["detections"][0]
    assert set(detection.keys()) == {
        "detection_id", "type", "risk_level", "action", "confidence", "needs_review", "bbox",
    }
    assert isinstance(detection["detection_id"], str) and detection["detection_id"]
    assert set(detection["bbox"].keys()) == {"x", "y", "width", "height"}

    assert set(body["verification"].keys()) == {"status", "attempts", "residual_count", "needs_human_review"}
    assert set(body["summary"].keys()) == {"total_detections", "critical_count", "needs_review_count", "blocked"}


def test_analyze_phone_canonicalization_holds_through_the_api(client, dataset_image):
    """Phase 6.3 regression, exercised through the API: RegexDetector's
    "PhoneTW" and ContextDetector's "Phone" for the same value must merge
    into ONE canonical "Phone" finding, not survive as a duplicate."""
    data = dataset_image("PhoneTW_clean.png")
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    body = r.json()
    phone_detections = [d for d in body["detections"] if d["type"] == "Phone"]
    assert len(phone_detections) == 1
    assert not any(d["type"] == "PhoneTW" for d in body["detections"])


def test_analyze_critical_type_gets_full_mask_action(client, dataset_image):
    data = dataset_image("TaiwanID_clean.png")
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    body = r.json()
    taiwan_id = next(d for d in body["detections"] if d["type"] == "TaiwanID")
    assert taiwan_id["risk_level"] == "CRITICAL"
    assert taiwan_id["action"] == "FULL_MASK"


def test_process_endpoint_matches_analyze_shape(client, dataset_image):
    data = dataset_image("Email_clean.png")
    r = client.post("/api/v1/process", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "status", "needs_human_review", "blocked", "detections", "verification", "summary", "review_token",
    }
