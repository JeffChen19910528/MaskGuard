"""Whole-Image Sensitive Data Sanity Scan (Phase 6.1 P0-2).

Root cause this addresses (Phase 6 OCR benchmark, 5 confirmed cases —
Passport_low_res, BankAccount_low_res/blurred/rotated/font_large): when
Detection finds NOTHING at all for an image, there are zero Detection
objects for VerificationEngine to re-check, so `verify_and_fix` correctly
reports PASSED *for the empty set it was asked to verify* — while the raw
sensitive value can still be sitting untouched in the final output. That is
not a bug in VerificationEngine's residual-matching logic (already hardened
in Phase 6.1's predecessor phase); it is `VerificationEngine` doing exactly
what it was asked, on a Detection result that was itself incomplete.

`WholeImageSanityScanner` closes that specific gap as an INDEPENDENT safety
net — never a replacement for Detection, never a second full Detection ->
Risk -> Policy run:

    Input
     ├── Detection -> Risk -> Policy -> Redaction   (unchanged, unaffected)
     │
     └── Independent Safety Path:
              Final output image -> fresh OCR -> fresh Regex/Context match
                                  -> SanityScanResult
                                  -> apply_sanity_scan() combines with
                                     VerificationEngine's own verdict

It reuses `RegexDetector`/`ContextDetector` (no duplicated regex patterns)
against a BRAND NEW OCR pass over the FINAL image, with no knowledge of
what the original Detection pass found, matched, or decided — it cannot be
biased by an earlier miss, because it has no access to the earlier result
at all.

Limits (do not oversell this): OCR itself can still fail to read a value in
the final image, so a clean scan is NOT proof the image contains no
sensitive data — it only prevents a *silent* PASS in the specific case this
was built for: Detection found zero candidates, but the raw value is still
recoverable by an unbiased second look. `apply_sanity_scan` reuses the
EXISTING `VerificationResult` status/`needs_human_review` fields — no new
status value is introduced anywhere in the codebase.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from PIL.Image import Image

from ..detection.context_detector import ContextDetector
from ..detection.regex_detector import RegexDetector
from ..ocr.base import IOcrEngine
from ..risk.intrinsic_critical import INTRINSIC_CRITICAL_TYPES
from .verification_engine import VerificationResult

# Additional types worth flagging beyond RiskEngine's own intrinsic-critical
# set (Skill.md §12 High tier) — the benchmark brief explicitly asked this
# scan to also cover Phone/Email, which RiskEngine treats as non-critical.
_ADDITIONAL_SCAN_TYPES = frozenset({"Email", "PhoneTW"})

#: Sensitive types this scan looks for. Deliberately reuses
#: `intrinsic_critical.INTRINSIC_CRITICAL_TYPES` (TaiwanID, Passport,
#: BankAccount, CreditCard, SecretKeyValue [covers Password/API Key/Secret
#: Key], BearerToken, JWT) rather than redefining that list — the "critical"
#: subset used below to decide FAIL vs. review-only is exactly that set.
SCAN_TYPES = INTRINSIC_CRITICAL_TYPES | _ADDITIONAL_SCAN_TYPES


@dataclass
class SanityScanResult:
    found_types: list[str] = field(default_factory=list)
    found_critical_types: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.found_types


class WholeImageSanityScanner:
    def __init__(self, ocr_engine: IOcrEngine, scan_types: frozenset[str] = SCAN_TYPES) -> None:
        self.ocr_engine = ocr_engine
        self.scan_types = scan_types

    def scan(self, image: Image, languages: list[str]) -> SanityScanResult:
        tokens = self.ocr_engine.recognize(image, languages)
        found = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
        relevant = [d for d in found if d.type in self.scan_types]

        found_types = sorted({d.type for d in relevant})
        critical_types = sorted({d.type for d in relevant if d.type in INTRINSIC_CRITICAL_TYPES})
        return SanityScanResult(found_types=found_types, found_critical_types=critical_types)


def apply_sanity_scan(verification_result: VerificationResult, scan_result: SanityScanResult) -> VerificationResult:
    """Combine the independent scan's evidence with VerificationEngine's own
    verdict. Never mutates either input (`dataclasses.replace` only), and
    never introduces a status value beyond the existing PASSED/FAILED +
    `needs_human_review` fields already defined on `VerificationResult`."""
    if scan_result.clean:
        return verification_result

    residual_types = sorted(set(verification_result.residual_types) | set(scan_result.found_types))

    if scan_result.found_critical_types:
        # Critical-type evidence still visible in the final output: this can
        # never resolve to a silent PASS, regardless of what
        # VerificationEngine itself concluded from the (possibly empty)
        # Detection result it was handed.
        return replace(
            verification_result,
            status="FAILED",
            needs_human_review=True,
            residual_count=max(verification_result.residual_count, len(scan_result.found_critical_types)),
            residual_types=residual_types,
        )

    # Non-critical (Email/PhoneTW) evidence: flag for human review without
    # forcing a hard FAIL — matches how existing non-critical detections are
    # treated elsewhere (blur/partial-mask territory, not full-block territory).
    return replace(verification_result, needs_human_review=True, residual_types=residual_types)
