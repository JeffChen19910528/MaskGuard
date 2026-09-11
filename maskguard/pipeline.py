"""Wires every engine into the pipeline mandated by Skill.md §2/§7/§41:

Image -> Preprocess -> OCR -> Detection -> Risk -> Policy -> Redaction
      -> Verification -> Metadata Strip -> Output + Report + Audit Log

Phase 6.1 P0-2 adds one more step after Verification: an INDEPENDENT
Whole-Image Sanity Scan (`verification.whole_image_sanity`) re-OCRs the
final image from scratch and checks it for high-risk sensitive-data shapes,
with no knowledge of what the original Detection pass found. This exists
only to catch the case Detection found nothing at all (confirmed by the
Phase 6 benchmark: Passport/BankAccount missed entirely under degraded
image conditions), so VerificationEngine trivially "PASSED" an empty
detection set while the raw value was still fully visible. It never
replaces or re-runs Detection/Risk/Policy, and never touches
VerificationEngine's own escalation logic — see `apply_sanity_scan()`.

Phase 6.1 P1 adds a lightweight deskew step BEFORE the main Detection-time
OCR call (confirmed by the Phase 6 benchmark: a mere 6-degree rotation
dropped recall to 0 for nearly every sensitive type). The deskewed image is
used ONLY to get better OCR tokens — `preprocessing.map_tokens_to_original`
immediately maps their bounding boxes back into the untouched original
image's coordinate space, so Detection/Risk/Policy/Redaction/Verification
all continue to operate on `image` (never on the deskewed copy) and their
existing coordinate-space invariant is unaffected.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL.Image import Image

from .audit import AuditLogger
from .config import Config
from .detection import (
    CandidateValueDetector,
    ContextDetector,
    KeywordDetector,
    LocalAiDetector,
    RegexDetector,
    UserRuleDetector,
    canonicalize_types,
    filter_unclaimed,
    load_user_rules,
)
from .metadata import strip_metadata
from .models import Detection
from .ocr.base import IOcrEngine
from .ocr.tesseract_engine import LocalOcrEngine
from .policy import PolicyEngine
from .preprocessing import deskew_for_ocr, load_and_normalize, map_tokens_to_original
from .redaction import RedactionEngine
from .risk import RiskEngine
from .verification import VerificationEngine, VerificationResult, WholeImageSanityScanner, apply_sanity_scan
from .report import build_report, write_report


class StrictModeBlockedError(RuntimeError):
    """Raised when Strict Mode (§40) requires blocking output after a failed verification."""


@dataclass
class ProcessResult:
    processing_id: str
    output_path: str | None
    report: dict
    verification: VerificationResult
    blocked: bool


class Pipeline:
    def __init__(self, config: Config, ocr_engine: IOcrEngine | None = None, user_rules_path: str | None = None) -> None:
        self.config = config
        self.ocr_engine = ocr_engine or LocalOcrEngine()
        self.redaction_engine = RedactionEngine()
        self.risk_engine = RiskEngine()
        self.policy_engine = PolicyEngine(config.masking, strict_mode=config.strict_mode)
        self.verification_engine = VerificationEngine(
            self.ocr_engine, self.redaction_engine, max_retries=config.masking.max_verification_retries
        )
        self.sanity_scanner = WholeImageSanityScanner(self.ocr_engine)
        self.user_rule_detector = UserRuleDetector(load_user_rules(user_rules_path) if user_rules_path else [])

        if config.strict_mode and self.ocr_engine.is_cloud:
            raise ValueError("Strict Mode forbids a cloud OCR engine (Skill.md §40)")

    def process(self, input_path: str, output_image_path: str, report_path: str, log_path: str) -> ProcessResult:
        processing_id = f"{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8]}"
        image = load_and_normalize(input_path)

        # Phase 6.1 P1: OCR sees a deskewed copy; every downstream stage
        # (Detection onward) sees `image` unchanged, with token bounding
        # boxes already mapped back into its coordinate space.
        deskewed = deskew_for_ocr(image)
        tokens = self.ocr_engine.recognize(deskewed.image, self.config.ocr.language)
        tokens = map_tokens_to_original(tokens, deskewed.image.size, deskewed.angle_degrees)

        detections, keyword_hits = self._detect(tokens)
        detections = self.risk_engine.score(detections, keyword_hits)
        detections = self.policy_engine.decide(detections)

        return self.redact_verify_and_finalize(processing_id, input_path, image, detections, output_image_path, report_path, log_path)

    def redact_verify_and_finalize(
        self,
        processing_id: str,
        input_path: str,
        image: Image,
        detections: list[Detection],
        output_image_path: str,
        report_path: str,
        log_path: str,
    ) -> ProcessResult:
        """The back half of `process()` — Redaction -> Verification ->
        Whole-Image Sanity Scan -> metadata strip -> output/report/audit —
        extracted as its own reusable entry point (Phase 8.3 §43).

        Why this exists: Human Review (`maskguard/api/review_service.py`)
        needs to run this EXACT tail against a `detections` list it built
        from a trusted, already-scored/decided source (a signed review
        context reconstructed from a prior `process()` run's own output,
        plus any newly Risk/Policy-scored manual additions — see
        review_service.py) rather than from a fresh OCR/Detection/Risk/
        Policy pass. Duplicating this ~35-line tail in the API layer would
        risk the review path's Verification/SanityScan/Strict-Mode-
        blocking/audit-logging behavior silently drifting from the normal
        path's over time; extracting it here instead guarantees both paths
        share the identical implementation. `process()`'s own behavior is
        byte-for-byte unchanged — every statement below is copied verbatim
        from what used to be the second half of `process()` — this is a
        pure extract-method refactor, not a semantic change, and every
        Core security engine call (Redaction/Verification/PolicyEngine's
        Strict-Mode-blocked decision) is untouched.
        """
        if self.config.masking.verification:
            redacted, verification = self.verification_engine.verify_and_fix(
                image, detections, self.config.ocr.language
            )
        else:
            redacted = self.redaction_engine.apply(image, detections)
            verification = VerificationResult(status="SKIPPED", attempts=0, residual_count=0)

        # Independent safety net (Phase 6.1 P0-2): runs unconditionally,
        # regardless of `masking.verification`, since its whole purpose is
        # catching what Detection-driven verification structurally cannot —
        # a Detection pass that found nothing at all. Also deskewed (P1) for
        # the same OCR-accuracy reason as the main pass; the scanner never
        # uses bounding boxes, so no coordinate mapping is needed here.
        sanity_input = deskew_for_ocr(redacted).image
        scan_result = self.sanity_scanner.scan(sanity_input, self.config.ocr.language)
        verification = apply_sanity_scan(verification, scan_result)

        blocked = self.config.strict_mode and verification.status == "FAILED"

        if not blocked:
            if not self.config.output.preserve_metadata:
                redacted = strip_metadata(redacted)
            Path(output_image_path).parent.mkdir(parents=True, exist_ok=True)
            redacted.save(output_image_path)
            final_output_path = output_image_path
        else:
            final_output_path = None  # Strict Mode: do NOT release the image (§40)

        report = build_report(processing_id, input_path, final_output_path or "", detections, verification)
        report["blocked"] = blocked
        write_report(report, report_path)

        AuditLogger(log_path).log_processing(processing_id, str(input_path), detections)

        return ProcessResult(
            processing_id=processing_id,
            output_path=final_output_path,
            report=report,
            verification=verification,
            blocked=blocked,
        )

    def _detect(self, tokens) -> tuple[list[Detection], list]:
        detections: list[Detection] = []
        keyword_hits = []

        if self.config.detection.enable_regex:
            detections.extend(RegexDetector().detect(tokens))
        if self.config.detection.enable_context:
            detections.extend(ContextDetector().detect(tokens))
        if self.config.detection.enable_context:
            # Phase 6.2: structural fallback for Passport/BankAccount when
            # the label itself is OCR-damaged (see detection/candidate_value.py).
            # `filter_unclaimed` drops any candidate that overlaps a region
            # some OTHER detector already classified — this fallback only
            # ever fills in a gap, never second-guesses an existing result.
            candidates = CandidateValueDetector().detect(tokens)
            detections.extend(filter_unclaimed(candidates, detections))
        if self.config.detection.enable_keyword:
            keyword_hits = KeywordDetector().detect(tokens)
        if self.config.detection.enable_ai:
            detections.extend(LocalAiDetector().detect(tokens, keyword_hits))

        detections.extend(self.user_rule_detector.detect(tokens))

        # Phase 6.3: normalize type identity (e.g. RegexDetector's "PhoneTW"
        # vs. ContextDetector's "Phone" for the same value) BEFORE Risk/Policy
        # ever see it, so RiskEngine._merge_overlapping's existing same-type
        # overlap dedup can actually merge the duplicate instead of scoring
        # it twice under two different type names. See detection/canonicalize.py.
        canonicalize_types(detections)
        return detections, keyword_hits
