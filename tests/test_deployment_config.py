"""Phase 9 §16/§17: production secret externalization + fail-closed startup
validation (maskguard/api/config.py, maskguard/api/review_token.py). Pure
unit tests — no Tesseract, no HTTP, no Docker."""
from __future__ import annotations

import pytest

from maskguard.api.config import InsecureProductionConfigError, validate_production_secret
from maskguard.api.review_token import ReviewTokenIssuer, TokenDetection


def test_development_mode_never_requires_a_secret():
    validate_production_secret("development", None)  # must not raise


@pytest.mark.parametrize("bad_secret", [None, "", "   ", "changeme", "CHANGEME", "default-secret", "abc123"])
def test_production_mode_rejects_missing_or_weak_secrets(bad_secret):
    with pytest.raises(InsecureProductionConfigError):
        validate_production_secret("production", bad_secret)


def test_production_mode_accepts_a_strong_secret():
    strong = "a" * 32
    validate_production_secret("production", strong)  # must not raise


def test_production_mode_rejects_a_secret_one_character_under_the_minimum():
    with pytest.raises(InsecureProductionConfigError):
        validate_production_secret("production", "a" * 31)


def test_review_token_issuer_uses_the_supplied_secret_not_a_random_one():
    secret = b"a fixed, operator-supplied 32+ byte secret!!"
    issuer_a = ReviewTokenIssuer(ttl_seconds=600, secret=secret)
    issuer_b = ReviewTokenIssuer(ttl_seconds=600, secret=secret)

    detection = TokenDetection(
        detection_id="d1", type="TaiwanID", risk_level="CRITICAL", action="FULL_MASK",
        confidence=0.9, needs_review=False, x=0, y=0, width=10, height=10,
    )
    token = issuer_a.issue([detection], 100, 100)

    # A DIFFERENT issuer instance constructed with the SAME explicit secret
    # must be able to verify it — proving the secret is genuinely shared/
    # supplied, not silently re-randomized per instance.
    context = issuer_b.verify_and_consume(token)
    assert context.detections[0].detection_id == "d1"


def test_review_token_issuer_without_a_secret_still_auto_generates_one():
    # Unchanged Phase 8.3/8.4 development behavior.
    issuer = ReviewTokenIssuer(ttl_seconds=600)
    assert issuer._secret and len(issuer._secret) == 32
