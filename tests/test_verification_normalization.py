"""P0-1 regression tests: Verification must not produce a false PASS when
the OCR reading at detection time and the OCR reading during verification
tokenize/space the same underlying value differently."""
from PIL import Image

from maskguard.models import BoundingBox, Detection, OcrToken, RedactionAction, RiskLevel
from maskguard.redaction import RedactionEngine
from maskguard.verification.normalization import normalize_for_detection, normalize_for_verification
from maskguard.verification.verification_engine import VerificationEngine


def test_credit_card_spacing_mismatch_normalizes_identically():
    assert normalize_for_detection("4111 1111 1111 1111", "CreditCard") == normalize_for_verification(
        "41111111 11111111", "CreditCard"
    )


def test_credit_card_dash_separated_normalizes_identically():
    assert normalize_for_detection("4111-1111-1111-1111", "CreditCard") == normalize_for_verification(
        "4111 1111 1111 1111", "CreditCard"
    )


def test_taiwan_id_spacing_variation_normalizes_identically():
    assert normalize_for_detection("A123456789", "TaiwanID") == normalize_for_verification(
        "A 123456789", "TaiwanID"
    )


def test_api_key_underscore_is_preserved_not_treated_as_separator():
    # Alphanumeric secrets must NOT have meaningful punctuation stripped —
    # only whitespace introduced by OCR tokenization.
    normalized = normalize_for_verification("demo_test_key_123456789", "SecretKeyValue")
    assert normalized == "demo_test_key_123456789"


class _FakeOcrEngine:
    """Returns a fixed token list for every crop, regardless of image content."""

    is_cloud = False

    def __init__(self, tokens: list[OcrToken]) -> None:
        self._tokens = tokens

    def recognize(self, image, languages):
        return self._tokens


def _tok(text: str, confidence: float = 0.95) -> OcrToken:
    return OcrToken(text=text, confidence=confidence, bounding_box=BoundingBox(0, 0, 40, 20))


def _credit_card_detection() -> Detection:
    return Detection(
        type="CreditCard",
        text="41111111 11111111",  # as first (mis-tokenized) OCR pass captured it
        confidence=0.93,
        bounding_box=BoundingBox(10, 10, 200, 20),
        risk_score=0.9,
        risk_level=RiskLevel.CRITICAL,
        action=RedactionAction.NONE,  # never actually redacted
    )


def test_residual_check_catches_credit_card_despite_retokenization():
    """THE P0-1 REPRO: original detection text came from a full-page OCR pass
    that mis-tokenized the card number as two 8-digit halves; the
    verification re-OCR of the (never-redacted) region reads it correctly as
    four 4-digit groups. A naive exact-string check would miss this. The
    fixed engine must still report it as residual (verification FAILS)."""
    detection = _credit_card_detection()
    fake_verification_ocr = _FakeOcrEngine(
        [_tok("4111"), _tok("1111"), _tok("1111"), _tok("1111")]
    )
    engine = VerificationEngine(fake_verification_ocr, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "FAILED", (
        "P0-1 regression: verification must FAIL when the raw value is still "
        "present, even though the two OCR passes tokenized it differently"
    )
    assert result.residual_count == 1


def test_residual_check_passes_when_region_genuinely_masked():
    detection = _credit_card_detection()
    detection.action = RedactionAction.FULL_MASK
    fake_verification_ocr = _FakeOcrEngine([])  # solid mask -> nothing recognizable
    engine = VerificationEngine(fake_verification_ocr, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "PASSED"
    assert result.residual_count == 0


def test_critical_detection_with_ambiguous_low_confidence_reocr_does_not_pass():
    """Fail-safe requirement #6: for CRITICAL data, an inconclusive re-OCR
    (non-empty, but low confidence) must not resolve to PASSED."""
    detection = _credit_card_detection()
    detection.action = RedactionAction.BLUR
    ambiguous_tokens = [_tok("4?1?", confidence=0.1), _tok("1?1?", confidence=0.15)]
    fake_verification_ocr = _FakeOcrEngine(ambiguous_tokens)
    engine = VerificationEngine(fake_verification_ocr, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "FAILED"
    assert result.needs_human_review is True


def test_non_critical_detection_with_ambiguous_low_confidence_reocr_can_pass():
    """The fail-safe UNKNOWN path is scoped to CRITICAL risk (§18 names
    Password/Key/Token/Credit-Card/ID-class data specifically) — a MEDIUM/
    HIGH detection with leftover low-confidence OCR noise (e.g. blur grain)
    should not be forced to escalate forever."""
    detection = Detection(
        type="Birthday",
        text="1999-01-01",
        confidence=0.75,
        bounding_box=BoundingBox(10, 10, 100, 20),
        risk_score=0.4,
        risk_level=RiskLevel.MEDIUM,
        action=RedactionAction.PARTIAL_MASK,
    )
    ambiguous_tokens = [_tok("l9?9", confidence=0.1)]
    fake_verification_ocr = _FakeOcrEngine(ambiguous_tokens)
    engine = VerificationEngine(fake_verification_ocr, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "PASSED"


def test_api_key_tokenization_mismatch_still_detected_as_residual():
    detection = Detection(
        type="SecretKeyValue",
        text="demo_test_key_123456789",
        confidence=0.9,
        bounding_box=BoundingBox(10, 10, 300, 20),
        risk_score=0.9,
        risk_level=RiskLevel.CRITICAL,
        action=RedactionAction.NONE,
    )
    # Verification OCR splits the key differently (e.g. around punctuation)
    # than the original detection pass did, but the underlying value — once
    # whitespace is stripped — is identical.
    fake_verification_ocr = _FakeOcrEngine([_tok("API_KEY=demo_test_key_123456789")])
    engine = VerificationEngine(fake_verification_ocr, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "FAILED"


def test_regex_rematch_catches_canonical_phone_type_after_alias_rewrite():
    """Phase 6.3 regression: `detection.type` can now be the canonical
    "Phone" (e.g. originally from ContextDetector, or from RegexDetector's
    "PhoneTW" already canonicalized upstream) while a fresh RegexDetector()
    call on the re-OCR crop still reports its own raw "PhoneTW" type. The
    (b)/(c) rematch comparison must canonicalize that fresh result too, or it
    silently stops catching residual phone numbers post-canonicalization."""
    detection = Detection(
        type="Phone",
        text="0912345678",
        confidence=0.85,
        bounding_box=BoundingBox(10, 10, 150, 20),
        risk_score=0.47,
        risk_level=RiskLevel.MEDIUM,
        action=RedactionAction.NONE,  # never actually redacted
    )
    # Re-OCR reads a DIFFERENT Taiwan phone number in the crop (still clearly
    # a phone number RegexDetector's PhoneTW pattern matches).
    fake_verification_ocr = _FakeOcrEngine([_tok("0987654321")])
    engine = VerificationEngine(fake_verification_ocr, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "FAILED", (
        "canonical-type rematch must still be recognized as the same "
        "sensitive category despite RegexDetector's raw 'PhoneTW' label"
    )


def test_regex_rematch_catches_same_type_value_with_different_text():
    """(b)/(c): even if the normalized-substring check somehow missed it, a
    fresh regex re-detection of the SAME sensitive type in the crop must
    still flag residual — e.g. OCR reads a different but still Luhn-valid
    16-digit run than the one originally captured."""
    detection = Detection(
        type="CreditCard",
        text="4111111111111111",
        confidence=0.9,
        bounding_box=BoundingBox(10, 10, 200, 20),
        risk_score=0.9,
        risk_level=RiskLevel.CRITICAL,
        action=RedactionAction.NONE,
    )
    # A different (but still Luhn-valid) card-shaped number than the needle.
    fake_verification_ocr = _FakeOcrEngine([_tok("5500 0000 0000 0004")])
    engine = VerificationEngine(fake_verification_ocr, RedactionEngine(), max_retries=1)

    image = Image.new("RGB", (300, 100), (255, 255, 255))
    redacted, result = engine.verify_and_fix(image, [detection], ["en"])

    assert result.status == "FAILED"
