"""Phase 6.1 P0-2 regression tests: WholeImageSanityScanner + apply_sanity_scan.

Confirms the scanner is independent of any prior Detection result, reuses
existing type vocabulary (no new status values), and that combining its
evidence with a VerificationResult never silently loses a critical finding.
"""
from maskguard.models import BoundingBox, OcrToken
from maskguard.ocr.base import IOcrEngine
from maskguard.verification import VerificationResult, apply_sanity_scan
from maskguard.verification.whole_image_sanity import SanityScanResult, WholeImageSanityScanner


class _FixedTokenEngine(IOcrEngine):
    is_cloud = False

    def __init__(self, tokens: list[OcrToken]) -> None:
        self._tokens = tokens

    def recognize(self, image, languages):
        return self._tokens


def _tok(text: str, x: int = 0, confidence: float = 0.9) -> OcrToken:
    return OcrToken(text=text, confidence=confidence, bounding_box=BoundingBox(x, 0, 100, 20))


# ---------------------------------------------------------------------------
# Scanner: independent detection of high-risk types from raw OCR tokens.
# ---------------------------------------------------------------------------


def test_scanner_finds_taiwan_id_from_fresh_ocr():
    scanner = WholeImageSanityScanner(_FixedTokenEngine([_tok("A123456789")]))
    result = scanner.scan(image=None, languages=["en"])
    assert "TaiwanID" in result.found_types
    assert "TaiwanID" in result.found_critical_types
    assert not result.clean


def test_scanner_finds_passport_via_context_label():
    scanner = WholeImageSanityScanner(_FixedTokenEngine([_tok("護照"), _tok("：", x=60), _tok("PA1234567", x=80)]))
    result = scanner.scan(image=None, languages=["zh-TW", "en"])
    assert "Passport" in result.found_critical_types


def test_scanner_finds_email_as_non_critical_type():
    scanner = WholeImageSanityScanner(_FixedTokenEngine([_tok("admin@example.com")]))
    result = scanner.scan(image=None, languages=["en"])
    assert "Email" in result.found_types
    assert "Email" not in result.found_critical_types  # flagged, but not "critical"


def test_scanner_reports_clean_when_nothing_sensitive_is_found():
    scanner = WholeImageSanityScanner(_FixedTokenEngine([_tok("hello"), _tok("world", x=60)]))
    result = scanner.scan(image=None, languages=["en"])
    assert result.clean


def test_scanner_reports_clean_when_ocr_returns_nothing():
    scanner = WholeImageSanityScanner(_FixedTokenEngine([]))
    result = scanner.scan(image=None, languages=["en"])
    assert result.clean


def test_scanner_ignores_types_outside_its_scan_types():
    # URL/IPAddress are real RegexDetector types, but not in SCAN_TYPES —
    # this scan is deliberately scoped to the high-risk list, not "anything
    # RegexDetector can find".
    scanner = WholeImageSanityScanner(_FixedTokenEngine([_tok("https://example.com/path")]))
    result = scanner.scan(image=None, languages=["en"])
    assert result.clean


# ---------------------------------------------------------------------------
# apply_sanity_scan: combining the scan's evidence with a VerificationResult
# without inventing new status values or silently dropping either input.
# ---------------------------------------------------------------------------


def _passed_result() -> VerificationResult:
    return VerificationResult(status="PASSED", attempts=1, residual_count=0)


def test_apply_sanity_scan_does_not_touch_a_clean_result():
    result = apply_sanity_scan(_passed_result(), SanityScanResult())
    assert result.status == "PASSED"
    assert result.needs_human_review is False
    assert result.residual_count == 0


def test_apply_sanity_scan_forces_failed_on_critical_finding():
    scan = SanityScanResult(found_types=["TaiwanID"], found_critical_types=["TaiwanID"])
    result = apply_sanity_scan(_passed_result(), scan)
    assert result.status == "FAILED"
    assert result.needs_human_review is True
    assert "TaiwanID" in result.residual_types


def test_apply_sanity_scan_flags_review_without_forcing_fail_on_non_critical_finding():
    scan = SanityScanResult(found_types=["Email"], found_critical_types=[])
    result = apply_sanity_scan(_passed_result(), scan)
    assert result.status == "PASSED"  # not force-failed
    assert result.needs_human_review is True  # but flagged
    assert "Email" in result.residual_types


def test_apply_sanity_scan_never_downgrades_an_already_failed_result():
    already_failed = VerificationResult(status="FAILED", attempts=3, residual_count=2, needs_human_review=True)
    result = apply_sanity_scan(already_failed, SanityScanResult())
    assert result.status == "FAILED"
    assert result.residual_count == 2


def test_apply_sanity_scan_merges_residual_types_without_duplicates():
    verification = VerificationResult(status="FAILED", attempts=1, residual_count=1, residual_types=["CreditCard"])
    scan = SanityScanResult(found_types=["CreditCard", "TaiwanID"], found_critical_types=["CreditCard", "TaiwanID"])
    result = apply_sanity_scan(verification, scan)
    assert result.residual_types == ["CreditCard", "TaiwanID"]


def test_apply_sanity_scan_does_not_mutate_its_inputs():
    verification = _passed_result()
    scan = SanityScanResult(found_types=["TaiwanID"], found_critical_types=["TaiwanID"])
    apply_sanity_scan(verification, scan)
    assert verification.status == "PASSED"  # original untouched
