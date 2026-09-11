"""Phase 10.4 §2/§43/§44/§98/§117: audit storage failure must never
weaken security — the underlying operation (authentication/authorization/
image processing) must complete normally regardless.
"""
from __future__ import annotations

from .conftest import login_as


def test_analyze_succeeds_even_when_audit_storage_cannot_initialize(client, ocr_env, dataset_image, tmp_path):
    """Points AUDIT_DB_PATH at a location that can never be created (a
    path component that is itself an existing FILE, so
    `Path(...).mkdir(parents=True)` fails) — simulates a real storage
    initialization failure (permission error / invalid path / etc.)
    without needing to actually exhaust disk space."""
    blocking_file = tmp_path / "not_a_directory"
    blocking_file.write_text("this occupies the path segment audit wants to use as a directory")
    from maskguard.api.audit.config import get_audit_settings
    from maskguard.api.audit.service import get_audit_store

    client.auth_runtime.settings  # sanity: fixture already built the app once
    import os

    os.environ["AUDIT_DB_PATH"] = str(blocking_file / "audit.db")  # parent IS a file — cannot become a directory
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()

    login_as(client, "reviewer-1")
    resp = client.post("/api/v1/analyze", files={"file": ("upload.png", dataset_image("TaiwanID_clean.png"), "image/png")})
    # The actual security-relevant operation (authenticate, authorize,
    # detect, classify, decide FULL_MASK) completes normally — a broken
    # audit store never surfaces as a request failure.
    assert resp.status_code == 200
    body = resp.json()
    assert body["detections"][0]["type"] == "TaiwanID"
    assert body["detections"][0]["action"] == "FULL_MASK"


def test_authorization_denial_still_works_when_audit_storage_is_broken(client, tmp_path):
    """§44: authorization's DENY behavior itself must be completely
    unaffected by a simultaneously-broken audit store — a broken audit
    system must never accidentally become a fail-OPEN for authorization."""
    blocking_file = tmp_path / "not_a_directory_2"
    blocking_file.write_text("blocks the audit directory")
    import os

    from maskguard.api.audit.config import get_audit_settings
    from maskguard.api.audit.service import get_audit_store

    os.environ["AUDIT_DB_PATH"] = str(blocking_file / "audit.db")
    get_audit_settings.cache_clear()
    get_audit_store.cache_clear()

    login_as(client, "operator-1")  # no review.* permission
    resp = client.post(
        "/api/v1/review",
        files={"file": ("upload.png", b"x", "image/png")},
        data={"review": '{"review_token": "x", "items": [{"detection_id": "d1", "review_status": "ACCEPTED"}]}'},
    )
    assert resp.status_code == 403  # still correctly denied
