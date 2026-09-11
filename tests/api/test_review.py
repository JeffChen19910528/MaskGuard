"""POST /api/v1/review (Phase 8.3 §37) — real Tesseract, real MaskGuard
Core, real Phase 6 dataset fixtures. No monkey-patching of Core to fake a
successful outcome; the few monkeypatches here are of the API-route/service
BOUNDARY only, to exercise infrastructure paths (like Strict-Mode blocking)
that are impractical to trigger organically with clean synthetic fixtures.
"""
from __future__ import annotations

import json
import logging

import pytest

from maskguard.api.config import ApiSettings, get_settings
from maskguard.api.dependencies import get_service

pytestmark = pytest.mark.usefixtures("ocr_env")


def _analyze(client, dataset_image, filename: str) -> dict:
    data = dataset_image(filename)
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    return r.json()


def _review(client, data: bytes, review_token: str, items: list[dict]):
    payload = json.dumps({"review_token": review_token, "items": items})
    return client.post("/api/v1/review", files={"file": ("upload.png", data, "image/png")}, data={"review": payload})


# ---------------------------------------------------------------------------
# 1-4: the browser cannot override risk/action/confidence/type.
# ---------------------------------------------------------------------------


def test_cannot_modify_risk_level_action_confidence_or_type(client, dataset_image):
    data = dataset_image("TaiwanID_clean.png")
    body = _analyze(client, dataset_image, "TaiwanID_clean.png")
    taiwan_id = body["detections"][0]
    assert taiwan_id["type"] == "TaiwanID"
    assert taiwan_id["risk_level"] == "CRITICAL"
    assert taiwan_id["action"] == "FULL_MASK"

    tampered_item = {
        "detection_id": taiwan_id["detection_id"],
        "review_status": "ACCEPTED",
        # None of these fields exist on ReviewItemRequest — Pydantic drops
        # them; this proves that structurally, not just behaviorally.
        "risk_level": "LOW",
        "action": "NONE",
        "confidence": 0.01,
        "type": "Unknown",
    }
    r = _review(client, data, body["review_token"], [tampered_item])
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"

    # The real proof: independently re-scan the produced image — if the
    # tampered fields had ANY effect, the Taiwan ID would still be visible.
    verify_r = client.post("/api/v1/verify", files={"file": ("out.png", r.content, "image/png")})
    assert verify_r.json()["clean"] is True


# ---------------------------------------------------------------------------
# 5-10: input validation.
# ---------------------------------------------------------------------------


def test_invalid_detection_id_rejected(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    r = _review(client, data, body["review_token"], [{"detection_id": "not-a-real-id", "review_status": "ACCEPTED"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_DETECTION"


def test_malformed_review_json_rejected(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    r = client.post(
        "/api/v1/review", files={"file": ("upload.png", data, "image/png")}, data={"review": "{not valid json"}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REVIEW"


@pytest.mark.parametrize(
    "bbox",
    [
        {"x": -5, "y": 0, "width": 10, "height": 10},  # negative
        {"x": 0, "y": 0, "width": 0, "height": 10},  # zero width
        {"x": 0, "y": 0, "width": -10, "height": 10},  # negative width
        {"x": 9999, "y": 9999, "width": 50, "height": 50},  # out of image bounds
    ],
)
def test_invalid_or_negative_or_out_of_bounds_bbox_rejected(client, dataset_image, bbox):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    r = _review(
        client, data, body["review_token"], [{"type": "Email", "bbox": bbox, "source": "MANUAL"}]
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_BBOX"


def test_unknown_manual_type_rejected(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    r = _review(
        client, data, body["review_token"],
        [{"type": "TotallyMadeUpType", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}, "source": "MANUAL"}],
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_DETECTION_TYPE"


def test_oversized_bbox_rejected(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    tiny_area_settings = ApiSettings(max_review_bbox_area_ratio=0.01)
    client.app.dependency_overrides[get_settings] = lambda: tiny_area_settings
    try:
        r = _review(
            client, data, body["review_token"],
            [{"type": "Email", "bbox": {"x": 0, "y": 0, "width": 500, "height": 500}, "source": "MANUAL"}],
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "INVALID_BBOX"
    finally:
        client.app.dependency_overrides.clear()


def test_undersized_bbox_rejected(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    r = _review(
        client, data, body["review_token"],
        [{"type": "Email", "bbox": {"x": 0, "y": 0, "width": 1, "height": 1}, "source": "MANUAL"}],
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_BBOX"


def test_image_mismatch_between_analyze_and_review_rejected(client, dataset_image):
    """A different image than the one analyzed must not silently reuse the
    prior review token's trusted detections."""
    body = _analyze(client, dataset_image, "Email_clean.png")
    other_image = dataset_image("TaiwanID_clean.png")
    r = _review(client, other_image, body["review_token"], [])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REVIEW"


# ---------------------------------------------------------------------------
# 11: expiration.
# ---------------------------------------------------------------------------


def test_expired_review_rejected(client, dataset_image):
    expiring_settings = ApiSettings(review_token_ttl_seconds=0)
    client.app.dependency_overrides[get_settings] = lambda: expiring_settings
    try:
        # get_service() is cached independent of settings overrides in this
        # test client's app instance, but the ISSUER reads ttl at issue
        # time from the settings dependency it was built with at app
        # construction — re-fetch a fresh service bound to this override.
        from maskguard.api.service import MaskGuardService

        service = MaskGuardService(review_token_ttl_seconds=0)
        client.app.dependency_overrides[get_service] = lambda: service

        data = dataset_image("Email_clean.png")
        r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
        token = r.json()["review_token"]

        import time

        time.sleep(0.05)
        r2 = _review(client, data, token, [])
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "REVIEW_EXPIRED"
    finally:
        client.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 12: critical rejection remains fail-safe.
# ---------------------------------------------------------------------------


def test_critical_rejection_keeps_the_mask_and_flags_for_review(client, dataset_image):
    data = dataset_image("TaiwanID_clean.png")
    body = _analyze(client, dataset_image, "TaiwanID_clean.png")
    taiwan_id = body["detections"][0]

    r = _review(
        client, data, body["review_token"],
        [{"detection_id": taiwan_id["detection_id"], "review_status": "REJECTED", "reason": "false positive"}],
    )
    assert r.status_code == 200
    assert r.headers["X-Review-Needs-Human-Review"] == "true"
    assert r.headers["X-Review-Status"] == "NEEDS_REVIEW"

    # Never: "user rejected it, therefore safe" — the value must still be masked.
    verify_r = client.post("/api/v1/verify", files={"file": ("out.png", r.content, "image/png")})
    assert verify_r.json()["clean"] is True


def test_non_critical_rejection_is_honored_and_drops_the_finding(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    email = body["detections"][0]
    assert email["risk_level"] != "CRITICAL"

    r = _review(
        client, data, body["review_token"],
        [{"detection_id": email["detection_id"], "review_status": "REJECTED", "reason": "not actually an email"}],
    )
    assert r.status_code == 200
    assert r.headers["X-Review-Detection-Count"] == "0"


# ---------------------------------------------------------------------------
# 13: verification failure must block output, never release an unsafe image.
# ---------------------------------------------------------------------------


def test_blocked_outcome_returns_json_never_a_fake_image(client, dataset_image, monkeypatch):
    """Exercises the route's own BLOCKED-handling branch by making the
    service layer report a withheld output (`image_bytes=None`) — the same
    shape Strict Mode produces — without needing to organically force a
    genuine Tesseract verification failure against a clean synthetic
    fixture (infrastructure test, not a faked SUCCESS)."""
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")

    from dataclasses import replace

    from maskguard.api.review_service import ReviewOutcome

    service = get_service()
    real_review = service.review

    def _blocked_review(*args, **kwargs):
        outcome, _image_bytes = real_review(*args, **kwargs)
        blocked_result = replace(outcome.process_result, blocked=True, output_path=None)
        blocked_outcome = ReviewOutcome(
            process_result=blocked_result, detection_ids=outcome.detection_ids,
            critical_rejection_occurred=outcome.critical_rejection_occurred, events=outcome.events,
        )
        return blocked_outcome, None

    monkeypatch.setattr(service, "review", _blocked_review)

    r = _review(client, data, body["review_token"], [])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    resp_body = r.json()
    assert resp_body["status"] == "BLOCKED"
    assert "image" not in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 14/15: no raw sensitive data in response or logs.
# ---------------------------------------------------------------------------


def test_no_raw_sensitive_data_in_review_response(client, dataset_image):
    data = dataset_image("APIKey_clean.png")
    body = _analyze(client, dataset_image, "APIKey_clean.png")
    secret = body["detections"][0]

    r = _review(client, data, body["review_token"], [{"detection_id": secret["detection_id"], "review_status": "ACCEPTED"}])
    # Response is a PNG (binary) — check headers text too.
    assert "demo_test_key_123456789" not in str(r.headers)


def test_no_raw_sensitive_data_or_reason_in_logs(client, dataset_image, caplog):
    caplog.set_level(logging.DEBUG)
    data = dataset_image("APIKey_clean.png")
    body = _analyze(client, dataset_image, "APIKey_clean.png")
    secret = body["detections"][0]

    sensitive_reason = "the real key is demo_test_key_123456789 trust me"
    _review(
        client, data, body["review_token"],
        [{"detection_id": secret["detection_id"], "review_status": "REJECTED", "reason": sensitive_reason}],
    )
    assert "demo_test_key_123456789" not in caplog.text
    assert sensitive_reason not in caplog.text


# ---------------------------------------------------------------------------
# 16: review reason length enforced.
# ---------------------------------------------------------------------------


def test_review_reason_length_is_enforced(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")
    email = body["detections"][0]

    too_long_reason = "x" * 5000
    r = _review(
        client, data, body["review_token"],
        [{"detection_id": email["detection_id"], "review_status": "REJECTED", "reason": too_long_reason}],
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REVIEW"


# ---------------------------------------------------------------------------
# 17: duplicate submission handled safely.
# ---------------------------------------------------------------------------


def test_duplicate_review_submission_is_rejected_not_reprocessed(client, dataset_image):
    data = dataset_image("Email_clean.png")
    body = _analyze(client, dataset_image, "Email_clean.png")

    r1 = _review(client, data, body["review_token"], [])
    assert r1.status_code == 200

    r2 = _review(client, data, body["review_token"], [])
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "REVIEW_CONFLICT"
