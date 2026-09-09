"""P0 security test (per the benchmark brief's "Important Security Test"):
OCR SEGMENTATION DIFFERENCE must never produce a Verification False PASS.

Example from the brief:
    Engine A reads: 4111111111111111
    Engine B reads: 4111 1111 1111 1111
Both must be treated as the SAME CreditCard value.

This exercises the real, unmodified `maskguard.verification.VerificationEngine`
and `normalize_for_verification` (the P0-1 fix) against two OCR engines that
deliberately segment the identical underlying value differently — simulating
what comparing Tesseract against a second engine (e.g. PaddleOCR) would look
like without requiring that second engine to be installed. No real OCR
binary is needed, so this always runs under plain `pytest` too (not just
`pytest -m benchmark`) — it is cheap, deterministic security-regression
protection, not just a benchmark curiosity.
"""
from __future__ import annotations

from PIL import Image

from maskguard.models import BoundingBox, Detection, OcrToken, RedactionAction, RiskLevel
from maskguard.ocr.base import IOcrEngine
from maskguard.redaction import RedactionEngine
from maskguard.verification import VerificationEngine


class _FixedTokenEngine(IOcrEngine):
    """Always returns the same fixed token list, standing in for "engine B"
    reading the same underlying image differently than "engine A" did."""

    is_cloud = False

    def __init__(self, tokens: list[OcrToken]) -> None:
        self._tokens = tokens

    def recognize(self, image, languages):
        return self._tokens


def _tok(text: str, x: int, confidence: float = 0.9) -> OcrToken:
    return OcrToken(text=text, confidence=confidence, bounding_box=BoundingBox(x=x, y=0, width=40, height=20))


def _unredacted_credit_card_detection(engine_a_text: str) -> Detection:
    return Detection(
        type="CreditCard",
        text=engine_a_text,  # as "Engine A" (detection time) read it
        confidence=0.9,
        bounding_box=BoundingBox(x=0, y=0, width=250, height=20),
        risk_score=0.9,
        risk_level=RiskLevel.CRITICAL,
        action=RedactionAction.NONE,  # deliberately never redacted, for this test
    )


def test_cross_engine_segmentation_is_treated_as_the_same_credit_card_value():
    """Engine A (detection time) reads "4111111111111111" as one contiguous
    token; Engine B (verification time) reads the SAME still-visible value
    as four spaced groups "4111 1111 1111 1111". Verification must FAIL
    (residual found) either way — the segmentation difference must never
    manufacture a false PASS."""
    detection = _unredacted_credit_card_detection("4111111111111111")

    engine_b = _FixedTokenEngine([_tok("4111", 0), _tok("1111", 50), _tok("1111", 100), _tok("1111", 150)])
    engine = VerificationEngine(engine_b, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    _redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "FAILED", (
        "cross-engine segmentation difference produced a Verification False "
        "PASS — Engine B's differently-spaced reading of the identical "
        "un-redacted value was not recognized as the same CreditCard"
    )


def test_cross_engine_segmentation_reverse_direction_also_fails_correctly():
    """Same property, tokenization direction reversed: Engine A (detection)
    read it spaced, Engine B (verification) reads it contiguous."""
    detection = _unredacted_credit_card_detection("4111 1111 1111 1111")

    engine_b = _FixedTokenEngine([_tok("4111111111111111", 0)])
    engine = VerificationEngine(engine_b, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    _redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "FAILED"


def test_cross_engine_segmentation_still_passes_once_genuinely_masked():
    """Sanity check on the other side of the property: once the region is
    ACTUALLY redacted, a differently-segmented (but low-confidence/garbled,
    consistent with a solid mask) Engine B reading must still let
    verification PASS — the fix must not make verification impossible to
    satisfy."""
    detection = _unredacted_credit_card_detection("4111111111111111")
    detection.action = RedactionAction.FULL_MASK

    engine_b = _FixedTokenEngine([])  # solid mask -> nothing recognizable
    engine = VerificationEngine(engine_b, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    _redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "PASSED"
