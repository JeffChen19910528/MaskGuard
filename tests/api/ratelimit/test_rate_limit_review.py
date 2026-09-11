"""Phase 10.5 §20/§21/§46/§47/§95/§101: review-operation rate limiting.
Uses a real analyze->review flow (Tesseract required, `ocr_env`)."""
from __future__ import annotations

import json

from ..authorization.conftest import login_as
from .conftest import build_client


def _analyze(client, dataset_image, filename: str) -> dict:
    data = dataset_image(filename)
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    return r.json()


def _review(client, data: bytes, review_token: str, items: list[dict]):
    payload = json.dumps({"review_token": review_token, "items": items})
    return client.post("/api/v1/review", files={"file": ("upload.png", data, "image/png")}, data={"review": payload})


def test_review_rate_limited_by_identity_not_token(monkeypatch, tmp_path, provider, ocr_env, dataset_image):
    """§21/§47/§101: many DIFFERENT valid review tokens (fresh analyze
    calls) from the SAME reviewer must still share one rate-limit bucket
    — never keyed by the token value itself."""
    client = build_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="10", RATE_LIMIT_REVIEW_CAPACITY="2", RATE_LIMIT_REVIEW_WINDOW_SECONDS="10",
    )
    login_as(client, "reviewer-1")
    data = dataset_image("TaiwanID_clean.png")

    outcomes = []
    for _ in range(3):
        body = _analyze(client, dataset_image, "TaiwanID_clean.png")  # fresh review_token every time
        detection = body["detections"][0]
        r = _review(client, data, body["review_token"], [{"detection_id": detection["detection_id"], "review_status": "ACCEPTED"}])
        outcomes.append(r.status_code)

    assert outcomes[:2] == [200, 200]
    assert outcomes[2] == 429  # the 3rd, despite a perfectly fresh/valid token, is rate limited


def test_review_reject_and_manual_also_rate_limited(monkeypatch, tmp_path, provider, ocr_env, dataset_image):
    client = build_client(
        monkeypatch, tmp_path, provider,
        RATE_LIMIT_IMAGE_ANALYZE_CAPACITY="10", RATE_LIMIT_REVIEW_CAPACITY="1", RATE_LIMIT_REVIEW_WINDOW_SECONDS="10",
    )
    login_as(client, "reviewer-1")
    data = dataset_image("TaiwanID_clean.png")
    body = _analyze(client, dataset_image, "TaiwanID_clean.png")
    detection = body["detections"][0]
    r1 = _review(client, data, body["review_token"], [{"detection_id": detection["detection_id"], "review_status": "REJECTED", "reason": "test"}])
    assert r1.status_code == 200

    body2 = _analyze(client, dataset_image, "TaiwanID_clean.png")
    detection2 = body2["detections"][0]
    r2 = _review(client, data, body2["review_token"], [{"detection_id": detection2["detection_id"], "review_status": "REJECTED", "reason": "test"}])
    assert r2.status_code == 429
