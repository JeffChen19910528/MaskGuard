"""Verification Engine (Skill.md §16, §36): re-runs OCR on the redacted image
and checks whether original sensitive text is still recoverable. On failure it
escalates the redaction method/area (via RedactionEngine.escalate) and retries.
For CRITICAL detections, residual detection must be exactly zero to pass (§36).

P0-1 fix: `_find_residual` no longer trusts an exact-string comparison
against the raw text captured at detection time (see `normalization.py` for
why that could produce a false PASS). It now checks, per detection:

  (a) normalized exact/substring matching (`normalize_for_verification`),
  (b) type-specific regex re-detection on the fresh re-OCR (reuses
      `RegexDetector`, which already includes format validation such as the
      Luhn check for credit cards) — catches a same-type sensitive value
      that reads differently but is still clearly present,
  (c) a fail-safe UNKNOWN outcome for CRITICAL-risk detections when the
      re-OCR is non-empty but too low-confidence to confidently call clean
      — per Skill.md §18/§36, "uncertain" must escalate/fail, never PASS.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from PIL import Image

from ..detection.canonicalize import canonicalize_types
from ..detection.regex_detector import RegexDetector
from ..models import Detection, OcrToken, RiskLevel
from ..ocr.base import IOcrEngine
from ..redaction.redaction_engine import RedactionEngine
from .normalization import normalize_for_verification

# Below this average per-token OCR confidence, a non-empty re-OCR result is
# treated as "Tesseract itself is unsure", not as "confidently clean".
_AMBIGUOUS_CONFIDENCE_THRESHOLD = 0.35


class _Outcome(enum.Enum):
    CLEAN = "CLEAN"
    FOUND = "FOUND"
    UNKNOWN = "UNKNOWN"


@dataclass
class VerificationResult:
    status: str  # "PASSED" | "FAILED"
    attempts: int
    residual_count: int
    needs_human_review: bool = False
    residual_types: list[str] = field(default_factory=list)


class VerificationEngine:
    def __init__(self, ocr_engine: IOcrEngine, redaction_engine: RedactionEngine, max_retries: int = 3) -> None:
        self.ocr_engine = ocr_engine
        self.redaction_engine = redaction_engine
        self.max_retries = max_retries

    def verify_and_fix(
        self,
        original_image: Image.Image,
        detections: list[Detection],
        languages: list[str],
    ) -> tuple[Image.Image, VerificationResult]:
        redacted = self.redaction_engine.apply(original_image, detections)

        for attempt in range(1, self.max_retries + 1):
            residual = self._find_residual(redacted, detections, languages)
            if not residual:
                return redacted, VerificationResult(status="PASSED", attempts=attempt, residual_count=0)

            if attempt == self.max_retries:
                needs_review = any(d.risk_level == RiskLevel.CRITICAL for d in residual)
                return redacted, VerificationResult(
                    status="FAILED",
                    attempts=attempt,
                    residual_count=len(residual),
                    needs_human_review=needs_review,
                    residual_types=[d.type for d in residual],
                )

            for detection in residual:
                self.redaction_engine.escalate(detection)
            redacted = self.redaction_engine.apply(original_image, detections)

        # Unreachable, kept for type-checkers.
        return redacted, VerificationResult(status="FAILED", attempts=self.max_retries, residual_count=-1)

    def _find_residual(
        self, redacted: Image.Image, detections: list[Detection], languages: list[str]
    ) -> list[Detection]:
        residual: list[Detection] = []
        for detection in detections:
            needle = detection.text.strip()
            if len(needle) < 3:
                continue
            box = detection.bounding_box
            padding = 6
            rect = (
                max(0, box.x - padding),
                max(0, box.y - padding),
                min(redacted.width, box.x + box.width + padding),
                min(redacted.height, box.y + box.height + padding),
            )
            if rect[2] <= rect[0] or rect[3] <= rect[1]:
                continue
            crop = redacted.crop(rect)
            crop_tokens = self.ocr_engine.recognize(crop, languages)

            outcome = self._assess_crop(detection, needle, crop_tokens)
            if outcome is _Outcome.FOUND:
                residual.append(detection)
            elif outcome is _Outcome.UNKNOWN and detection.risk_level == RiskLevel.CRITICAL:
                # Fail-safe (§18/§36): an inconclusive re-OCR of CRITICAL data
                # must escalate, never be treated as a clean pass.
                detection.needs_review = True
                residual.append(detection)
        return residual

    def _assess_crop(self, detection: Detection, needle: str, crop_tokens: list[OcrToken]) -> _Outcome:
        recovered_text = " ".join(t.text for t in crop_tokens)

        # (a) Normalized exact/substring match — the P0-1 fix. Both sides go
        # through the SAME canonicalization so a different OCR tokenization/
        # spacing of the identical underlying value can no longer hide it.
        normalized_needle = normalize_for_verification(needle, detection.type)
        normalized_recovered = normalize_for_verification(recovered_text, detection.type)
        if normalized_needle and normalized_needle in normalized_recovered:
            return _Outcome.FOUND

        # (b)/(c) Type-specific regex re-detection (includes e.g. the Luhn
        # check for CreditCard) — catches a same-type sensitive value that
        # OCR'd into a *different* but still clearly sensitive reading.
        # `detection.type` may already be a Phase 6.3 canonical type (e.g.
        # "Phone") while a fresh RegexDetector() call still reports its own
        # raw type (e.g. "PhoneTW") — canonicalize the rematches too, or this
        # comparison silently stops catching residual matches for any type
        # that canonicalization renames.
        rematches = canonicalize_types(RegexDetector().detect(crop_tokens))
        if any(m.type == detection.type for m in rematches):
            return _Outcome.FOUND

        if not crop_tokens:
            return _Outcome.CLEAN  # nothing recognizable — consistent with a solid mask

        avg_confidence = sum(t.confidence for t in crop_tokens) / len(crop_tokens)
        if avg_confidence < _AMBIGUOUS_CONFIDENCE_THRESHOLD:
            return _Outcome.UNKNOWN  # Tesseract itself is unsure what's left in this region

        return _Outcome.CLEAN
