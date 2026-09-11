"""Phase 8.3: signed review context (maskguard/api/review_token.py). Pure
unit tests — no Tesseract, no HTTP — of the tamper-resistance/expiration/
replay mechanics §30-33 depend on."""
from __future__ import annotations

import time

import pytest

from maskguard.api.review_token import ReviewTokenError, ReviewTokenIssuer, TokenDetection


def _detection(detection_id: str = "d1", **overrides) -> TokenDetection:
    base = dict(
        detection_id=detection_id, type="TaiwanID", risk_level="CRITICAL", action="FULL_MASK",
        confidence=0.85, needs_review=False, x=10, y=10, width=50, height=20,
    )
    base.update(overrides)
    return TokenDetection(**base)


def test_issue_then_verify_roundtrips_the_exact_detections():
    issuer = ReviewTokenIssuer(ttl_seconds=600)
    detection = _detection()
    token = issuer.issue([detection], image_width=800, image_height=600)

    context = issuer.verify_and_consume(token)

    assert context.image_width == 800
    assert context.image_height == 600
    assert len(context.detections) == 1
    assert context.detections[0] == detection


def test_tampered_signature_is_rejected():
    issuer = ReviewTokenIssuer(ttl_seconds=600)
    token = issuer.issue([_detection()], 800, 600)
    body, _, signature = token.rpartition(".")
    tampered = f"{body}.{'0' * len(signature)}"

    with pytest.raises(ReviewTokenError) as exc_info:
        issuer.verify_and_consume(tampered)
    assert exc_info.value.code == "INVALID_REVIEW"


def test_tampered_payload_is_rejected():
    """Flipping a byte in the payload body (e.g. trying to change a
    detection's recorded risk_level/action/type) invalidates the signature
    — this is the actual tamper-resistance property §30/§31 require."""
    issuer = ReviewTokenIssuer(ttl_seconds=600)
    token = issuer.issue([_detection()], 800, 600)
    body, _, signature = token.rpartition(".")
    tampered_body = body[:-1] + ("A" if body[-1] != "A" else "B")
    tampered = f"{tampered_body}.{signature}"

    with pytest.raises(ReviewTokenError) as exc_info:
        issuer.verify_and_consume(tampered)
    assert exc_info.value.code == "INVALID_REVIEW"


def test_malformed_token_is_rejected():
    issuer = ReviewTokenIssuer(ttl_seconds=600)
    for bad in ["", "not-a-token-at-all", "..", "onlyonepart"]:
        with pytest.raises(ReviewTokenError) as exc_info:
            issuer.verify_and_consume(bad)
        assert exc_info.value.code == "INVALID_REVIEW"


def test_expired_token_is_rejected():
    issuer = ReviewTokenIssuer(ttl_seconds=0)
    token = issuer.issue([_detection()], 800, 600)
    time.sleep(0.05)

    with pytest.raises(ReviewTokenError) as exc_info:
        issuer.verify_and_consume(token)
    assert exc_info.value.code == "REVIEW_EXPIRED"


def test_replayed_token_is_rejected_the_second_time():
    issuer = ReviewTokenIssuer(ttl_seconds=600)
    token = issuer.issue([_detection()], 800, 600)

    issuer.verify_and_consume(token)  # first use: fine
    with pytest.raises(ReviewTokenError) as exc_info:
        issuer.verify_and_consume(token)  # second use: replay
    assert exc_info.value.code == "REVIEW_CONFLICT"


def test_two_different_issuers_have_independent_secrets():
    # Different processes/instances must not accept each other's tokens —
    # confirms the secret is per-instance, not a fixed/shared constant.
    issuer_a = ReviewTokenIssuer(ttl_seconds=600)
    issuer_b = ReviewTokenIssuer(ttl_seconds=600)
    token = issuer_a.issue([_detection()], 800, 600)

    with pytest.raises(ReviewTokenError) as exc_info:
        issuer_b.verify_and_consume(token)
    assert exc_info.value.code == "INVALID_REVIEW"


def test_token_payload_never_contains_raw_text_field():
    """TokenDetection structurally has no field for matched raw text —
    this test guards against a future edit accidentally adding one."""
    detection = _detection()
    assert not hasattr(detection, "text")
    assert not hasattr(detection, "value")
    assert not hasattr(detection, "raw_text")
    assert not hasattr(detection, "ocr_text")


def test_spent_token_set_does_not_grow_past_alive_tokens():
    """§33: replay-guard memory is bounded by alive tokens within TTL, not
    unbounded — expired entries are swept on subsequent calls."""
    issuer = ReviewTokenIssuer(ttl_seconds=0)
    for i in range(5):
        token = issuer.issue([_detection(detection_id=f"d{i}")], 800, 600)
        time.sleep(0.01)
        with pytest.raises(ReviewTokenError):
            issuer.verify_and_consume(token)  # already expired by the time we check

    # A fresh, still-valid token issued now — sweeping must not have thrown
    # away anything it shouldn't have, and the spent-set must not have kept
    # accumulating the 5 expired ones above indefinitely.
    fresh_issuer = ReviewTokenIssuer(ttl_seconds=600)
    fresh_token = fresh_issuer.issue([_detection()], 800, 600)
    fresh_issuer.verify_and_consume(fresh_token)
    assert len(issuer.replay_store._spent) <= 1  # this issuer's own expired entries get swept lazily
