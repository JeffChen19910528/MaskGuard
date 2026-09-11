"""Pydantic API response schemas (Phase 8.1 §22/§23).

These are the API's OWN contract, kept deliberately separate from Core's
internal dataclasses (`maskguard.models.Detection`, `VerificationResult`,
the `report_builder.build_report()` dict shape). Mapping from Core to these
schemas happens explicitly in `mapping.py` field-by-field — never
`SomeSchema(**core_object.__dict__)` — so Core can evolve without silently
changing the API contract, and so a field Core adds later (or already
excludes, like `Detection.text`) doesn't leak here by accident.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    api_version: str
    app_version: str
    ocr_engine_available: bool


class BBoxResponse(BaseModel):
    x: int
    y: int
    width: int
    height: int


class DetectionResponse(BaseModel):
    """Deliberately excludes any raw matched text — `Detection.text` is
    never read by this schema (see mapping.py). Only type/risk/action/
    region, matching what `report_builder.build_report()` already exposes
    to the audit log/report (Skill.md §22/§25).

    `detection_id` (Phase 8.3 §6) is a server-generated UUID4 — never
    derived from OCR text, a filename, or anything else sensitive — the
    frontend-safe handle a Human Review submission references to accept or
    reject THIS specific finding.
    """

    detection_id: str
    type: str
    risk_level: str
    action: str
    confidence: float
    needs_review: bool
    bbox: BBoxResponse


class VerificationResponse(BaseModel):
    status: str
    attempts: int
    residual_count: int
    needs_human_review: bool


class SummaryResponse(BaseModel):
    total_detections: int
    critical_count: int
    needs_review_count: int
    blocked: bool


class AnalyzeResponse(BaseModel):
    status: str = Field(..., description="Overall outcome: PASSED, FAILED, NEEDS_REVIEW, SKIPPED, or BLOCKED")
    needs_human_review: bool
    blocked: bool
    detections: list[DetectionResponse]
    verification: VerificationResponse
    summary: SummaryResponse
    #: Phase 8.3: present on `/analyze` and `/process` responses only (not
    #: `/review`'s own response, which reuses this same schema but has
    #: nothing further to review). Opaque, signed, short-lived — pass it
    #: back to `POST /api/v1/review` to act on these exact detections.
    review_token: str | None = None


class VerifyResponse(BaseModel):
    """Independent whole-image sanity check (`WholeImageSanityScanner`) —
    NOT tied to a prior Detection/Risk/Policy run. See routes/images.py for
    why this endpoint deliberately does not reuse `VerificationEngine`."""

    clean: bool
    found_types: list[str]
    found_critical_types: list[str]


class ReviewItemRequest(BaseModel):
    """One line of a Human Review submission (Phase 8.3 §17). Exactly one
    of two shapes, distinguished by which fields are present:

    - Accept/reject an EXISTING automatic detection: `detection_id` +
      `review_status` (+ optional `reason` when rejecting). The browser
      does NOT send — and this schema has no field for — a type/risk/
      action/confidence override; see review_service.py, which resolves
      the real values from the signed review token, never from this
      request (§30/§31).
    - Add a NEW manual detection: `source="MANUAL"` + `type` + `bbox`. The
      backend computes its risk/action via the real RiskEngine/PolicyEngine
      (§10) — this request only ever supplies WHERE and WHAT KIND, never
      how it should be redacted.

    Any other field the client includes (e.g. a `risk_level` on either
    shape) is simply not part of this model and is dropped by Pydantic —
    review_service.py never reads request data through any path that could
    resurrect it.
    """

    detection_id: str | None = None
    review_status: Literal["ACCEPTED", "REJECTED"] | None = None
    reason: str | None = None

    type: str | None = None
    bbox: BBoxResponse | None = None
    source: Literal["MANUAL"] | None = None


class ReviewSubmissionRequest(BaseModel):
    review_token: str
    items: list[ReviewItemRequest] = Field(default_factory=list)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
