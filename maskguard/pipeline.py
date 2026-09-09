"""Wires every engine into the pipeline mandated by Skill.md §2/§7/§41:

Image -> Preprocess -> OCR -> Detection -> Risk -> Policy -> Redaction
      -> Verification -> Metadata Strip -> Output + Report + Audit Log
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .audit import AuditLogger
from .config import Config
from .detection import (
    ContextDetector,
    KeywordDetector,
    LocalAiDetector,
    RegexDetector,
    UserRuleDetector,
    load_user_rules,
)
from .metadata import strip_metadata
from .models import Detection
from .ocr.base import IOcrEngine
from .ocr.tesseract_engine import LocalOcrEngine
from .policy import PolicyEngine
from .preprocessing import load_and_normalize
from .redaction import RedactionEngine
from .risk import RiskEngine
from .verification import VerificationEngine, VerificationResult
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
        self.user_rule_detector = UserRuleDetector(load_user_rules(user_rules_path) if user_rules_path else [])

        if config.strict_mode and self.ocr_engine.is_cloud:
            raise ValueError("Strict Mode forbids a cloud OCR engine (Skill.md §40)")

    def process(self, input_path: str, output_image_path: str, report_path: str, log_path: str) -> ProcessResult:
        processing_id = f"{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8]}"
        image = load_and_normalize(input_path)

        tokens = self.ocr_engine.recognize(image, self.config.ocr.language)
        detections, keyword_hits = self._detect(tokens)
        detections = self.risk_engine.score(detections, keyword_hits)
        detections = self.policy_engine.decide(detections)

        if self.config.masking.verification:
            redacted, verification = self.verification_engine.verify_and_fix(
                image, detections, self.config.ocr.language
            )
        else:
            redacted = self.redaction_engine.apply(image, detections)
            verification = VerificationResult(status="SKIPPED", attempts=0, residual_count=0)

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
        if self.config.detection.enable_keyword:
            keyword_hits = KeywordDetector().detect(tokens)
        if self.config.detection.enable_ai:
            detections.extend(LocalAiDetector().detect(tokens, keyword_hits))

        detections.extend(self.user_rule_detector.detect(tokens))
        return detections, keyword_hits
