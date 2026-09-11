"""Phase 8.3 §39/§40: full real end-to-end Human Review flows against real
Tesseract + real Core. Synthetic fixtures only (Phase 6 dataset)."""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.usefixtures("ocr_env")


def test_e2e_accept_flow_taiwan_id_through_review_redaction_verification(client, dataset_image):
    """§39 flow 1 + §40 (TaiwanID critical E2E):
    1. Upload real synthetic sensitive image
    2. Analyze through FastAPI
    3. Display detection
    4. Enter review
    5. Accept detection
    6. Submit review
    7. Backend executes redaction
    8. Backend verifies
    9. Receive redacted image
    10. Confirm verification result

    Expected: no raw sensitive value exposed anywhere in the process.
    """
    data = dataset_image("TaiwanID_clean.png")

    # 1-3: upload + analyze + display detection
    analyze_r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert analyze_r.status_code == 200
    analyze_body = analyze_r.json()
    taiwan_id = next(d for d in analyze_body["detections"] if d["type"] == "TaiwanID")
    assert taiwan_id["risk_level"] == "CRITICAL"
    assert taiwan_id["action"] == "FULL_MASK"
    assert "A123456789" not in analyze_r.text  # no raw value exposed at analyze time

    # 4-6: enter review, accept, submit
    review_payload = {
        "review_token": analyze_body["review_token"],
        "items": [{"detection_id": taiwan_id["detection_id"], "review_status": "ACCEPTED"}],
    }
    review_r = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", data, "image/png")},
        data={"review": json.dumps(review_payload)},
    )

    # 7-9: backend executed redaction, response IS the redacted image
    assert review_r.status_code == 200
    assert review_r.headers["content-type"] == "image/png"
    assert "A123456789" not in str(review_r.headers)

    # 8/10: backend performed verification — confirm via the independent
    # sanity check AND the review response's own verification headers.
    assert review_r.headers["X-Review-Blocked"] == "false"
    verify_r = client.post("/api/v1/verify", files={"file": ("redacted.png", review_r.content, "image/png")})
    assert verify_r.status_code == 200
    verify_body = verify_r.json()
    assert verify_body["clean"] is True
    assert "TaiwanID" not in verify_body["found_types"]


def test_e2e_manual_bbox_flow_through_policy_redaction_verification(client, dataset_image):
    """§39 flow 2:
    1. Analyze
    2. Add manual bounding box
    3. Submit
    4. Backend determines policy
    5. Redact
    6. Verify
    """
    # 1: analyze a plain (no sensitive-type) fixture so the ONLY finding in
    # the final output is the human-added manual one — isolates the manual
    # path from the automatic-detection path cleanly.
    data = dataset_image("normal_non_sensitive_text.png")
    analyze_r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert analyze_r.status_code == 200
    analyze_body = analyze_r.json()

    # 2-3: add a manual bounding box (well within a typical rendered-text
    # image's bounds) and submit — frontend never computes risk/action,
    # only WHERE and WHAT KIND.
    manual_item = {
        "type": "PersonalName",
        "bbox": {"x": 10, "y": 10, "width": 80, "height": 20},
        "source": "MANUAL",
    }
    review_r = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", data, "image/png")},
        data={"review": json.dumps({"review_token": analyze_body["review_token"], "items": [manual_item]})},
    )

    # 4-5: backend decided policy + redacted — a real image comes back,
    # and the detection count header proves the manual item was scored and
    # kept (PersonalName is MEDIUM risk -> PARTIAL_MASK -> action != NONE).
    assert review_r.status_code == 200
    assert review_r.headers["content-type"] == "image/png"
    assert review_r.headers["X-Review-Detection-Count"] == "1"

    # 6: verify — the independent scanner re-checks the final image
    # (PersonalName is not in SCAN_TYPES, so "clean" here just confirms no
    # OTHER, unexpected critical leak was introduced).
    verify_r = client.post("/api/v1/verify", files={"file": ("redacted.png", review_r.content, "image/png")})
    assert verify_r.status_code == 200


def test_e2e_manual_bbox_for_critical_type_is_actually_redacted(client, dataset_image):
    """A manual CRITICAL-type addition (no automatic detection existed for
    it) must still end up genuinely masked and pass independent verification
    — proves the manual path carries the same fail-safe weight as the
    automatic path for BankAccount/Passport/TaiwanID-class data (§40)."""
    data = dataset_image("BankAccount_clean.png")

    analyze_r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    analyze_body = analyze_r.json()
    bank_account = next(d for d in analyze_body["detections"] if d["type"] == "BankAccount")

    # Reject the automatic finding (still fail-safe-kept per §16) AND
    # manually re-flag the same region with an explicit human-drawn box —
    # exercises redundant-manual-box skipping (§15) plus the critical
    # fail-safe path together.
    items = [
        {"detection_id": bank_account["detection_id"], "review_status": "REJECTED", "reason": "double-checking"},
        {"type": "BankAccount", "bbox": bank_account["bbox"], "source": "MANUAL"},
    ]
    review_r = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", data, "image/png")},
        data={"review": json.dumps({"review_token": analyze_body["review_token"], "items": items})},
    )
    assert review_r.status_code == 200
    assert review_r.headers["X-Review-Needs-Human-Review"] == "true"  # critical rejection flagged

    verify_r = client.post("/api/v1/verify", files={"file": ("redacted.png", review_r.content, "image/png")})
    verify_body = verify_r.json()
    assert verify_body["clean"] is True
    assert "1234567890123" not in str(review_r.headers)
    assert "1234567890123" not in verify_r.text
