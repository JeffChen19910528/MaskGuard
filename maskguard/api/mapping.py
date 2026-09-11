"""Core -> API schema conversion (Phase 8.1 §23). The ONLY place Core
result shapes are translated into the API's own Pydantic contract — every
route handler calls into here rather than touching `result.report` fields
directly, so there is exactly one spot to audit for "does this ever expose
raw sensitive text" (answer: no — `report_builder.build_report()` already
excludes `Detection.text`/`Detection`'s raw value from the dict this reads,
and this module never reaches past that dict for anything else).
"""
from __future__ import annotations

from ..pipeline import ProcessResult
from ..verification.whole_image_sanity import SanityScanResult
from .schemas import (
    AnalyzeResponse,
    BBoxResponse,
    DetectionResponse,
    SummaryResponse,
    VerificationResponse,
    VerifyResponse,
)


def _overall_status(result: ProcessResult) -> str:
    if result.blocked:
        return "BLOCKED"
    if result.verification.needs_human_review:
        return "NEEDS_REVIEW"
    return result.verification.status


def to_analyze_response(
    result: ProcessResult, detection_ids: list[str], review_token: str | None = None
) -> AnalyzeResponse:
    """`detection_ids` must be the same length, same order, as
    `result.report["detections"]` (Phase 8.3 §6) — callers generate these
    (see routes/images.py, routes/review.py) rather than this function
    inventing them, so the SAME ids used to mint/verify a review token
    (review_token.py) are exactly the ids shown to the client here."""
    detections = [
        DetectionResponse(
            detection_id=detection_id,
            type=d["type"],
            risk_level=d["risk"],
            action=d["action"],
            confidence=d["confidence"],
            needs_review=d["needs_review"],
            bbox=BBoxResponse(x=d["region"][0], y=d["region"][1], width=d["region"][2], height=d["region"][3]),
        )
        for d, detection_id in zip(result.report["detections"], detection_ids, strict=True)
    ]

    verification = VerificationResponse(
        status=result.verification.status,
        attempts=result.verification.attempts,
        residual_count=result.verification.residual_count,
        needs_human_review=result.verification.needs_human_review,
    )

    summary = SummaryResponse(
        total_detections=len(detections),
        critical_count=sum(1 for d in detections if d.risk_level == "CRITICAL"),
        needs_review_count=sum(1 for d in detections if d.needs_review),
        blocked=result.blocked,
    )

    return AnalyzeResponse(
        status=_overall_status(result),
        needs_human_review=result.verification.needs_human_review,
        blocked=result.blocked,
        detections=detections,
        verification=verification,
        summary=summary,
        review_token=review_token,
    )


def to_verify_response(scan: SanityScanResult) -> VerifyResponse:
    return VerifyResponse(
        clean=scan.clean,
        found_types=list(scan.found_types),
        found_critical_types=list(scan.found_critical_types),
    )
