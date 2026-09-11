"""Human Review orchestration (Phase 8.3). The ONLY place a review
submission is turned into a Core `Detection` list and run through the real
Redaction/Verification tail (`Pipeline.redact_verify_and_finalize` —
pipeline.py). No Detection/Risk/Policy/Redaction/Verification ALGORITHM is
implemented here — RiskEngine/PolicyEngine are called exactly as
`Pipeline.process()` itself calls them, never reimplemented.

Trust boundary (§30/§31 — read this before touching accept/reject logic):
for an EXISTING automatic detection, the browser submits only a
`detection_id` + `review_status` (+ optional `reason`) — this module
resolves the REAL type/bbox/risk_level/action/confidence for that id from
the signed, already-verified `ReviewContext` (review_token.py), never from
anything else the request body might contain. A brand-new MANUAL
detection's `type`/`bbox` IS attacker-influenced input (the whole point of
manual review), so it is validated here and then scored by the real
RiskEngine/PolicyEngine — its risk/action are Core-computed, never
client-supplied, exactly like every other detector's output.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from PIL.Image import Image

from ..models import BoundingBox, Detection, RedactionAction, RiskLevel
from ..pipeline import Pipeline, ProcessResult
from ..risk.intrinsic_critical import INTRINSIC_CRITICAL_TYPES
from .config import ApiSettings
from .errors import ApiError
from .review_token import ReviewContext, TokenDetection
from .schemas import ReviewItemRequest

#: Types a human reviewer may manually flag (§11). A deliberate, curated
#: subset of Core's real detector type vocabulary (risk/risk_engine.py's
#: `_BASE_SCORE` keys) — excludes non-PII technical types (URL, IPAddress)
#: that manual review has no reason to add. Frontend renders a dropdown
#: built from exactly this list (server-authoritative, §11: "Frontend must
#: never be authoritative").
REVIEWABLE_MANUAL_TYPES: frozenset[str] = frozenset(
    {
        "TaiwanID", "Passport", "BankAccount", "CreditCard",
        "SecretKeyValue", "BearerToken", "JWT",
        "Email", "Phone", "PersonalName", "Address",
    }
)

#: A human-drawn box gets maximum confidence — not because the frontend
#: says so (it CAN'T; ReviewItemRequest has no confidence field at all),
#: but because a human visually confirmed both the region and the type.
#: Combined with the real RiskEngine formula (base_score * confidence),
#: every intrinsically-critical type's own base score (>= 0.85) already
#: clears the 0.80 CRITICAL threshold at this confidence — no change to
#: RiskEngine/intrinsic_critical.py was needed to make manual CRITICAL
#: findings score CRITICAL (verified: TaiwanID 0.90, Passport 0.88,
#: BankAccount 0.85, CreditCard 0.90, SecretKeyValue/JWT 0.95, BearerToken
#: 0.90 — all >= 0.80 at confidence=1.0).
_MANUAL_DETECTION_CONFIDENCE = 1.0


class ReviewValidationError(ApiError):
    pass


def invalid_review(message: str) -> ReviewValidationError:
    return ReviewValidationError(message, code="INVALID_REVIEW", status_code=422)


def unknown_detection(message: str) -> ReviewValidationError:
    return ReviewValidationError(message, code="UNKNOWN_DETECTION", status_code=422)


def invalid_bbox(message: str) -> ReviewValidationError:
    return ReviewValidationError(message, code="INVALID_BBOX", status_code=422)


def invalid_detection_type(message: str) -> ReviewValidationError:
    return ReviewValidationError(message, code="INVALID_DETECTION_TYPE", status_code=422)


@dataclass
class ReviewOutcome:
    process_result: ProcessResult
    detection_ids: list[str]  # parallel to process_result.report["detections"], same order (§6)
    critical_rejection_occurred: bool
    events: list[dict]  # Phase 8.3 §28 — whitelisted-field-only, in-memory only, never persisted


def _boxes_overlap(a: BoundingBox, b: BoundingBox) -> bool:
    ax0, ay0, ax1, ay1 = a.x, a.y, a.x + a.width, a.y + a.height
    bx0, by0, bx1, by1 = b.x, b.y, b.x + b.width, b.y + b.height
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _validate_manual_bbox(item: ReviewItemRequest, context: ReviewContext, settings: ApiSettings) -> BoundingBox:
    bbox = item.bbox
    if bbox is None:
        raise invalid_review("A MANUAL review item requires a bbox.")

    x, y, width, height = bbox.x, bbox.y, bbox.width, bbox.height
    for name, value in (("x", x), ("y", y), ("width", width), ("height", height)):
        # Pydantic's `int` field already rejects NaN/Infinity/non-numeric
        # JSON at the schema layer (422 VALIDATION_ERROR) before this
        # function ever runs — these are the remaining SEMANTIC checks
        # (§12) a type-correct integer can still fail.
        if not isinstance(value, int):
            raise invalid_bbox(f"bbox.{name} must be an integer.")

    if x < 0 or y < 0:
        raise invalid_bbox("bbox x/y must be >= 0.")
    if width <= 0 or height <= 0:
        raise invalid_bbox("bbox width/height must be > 0.")
    if x + width > context.image_width or y + height > context.image_height:
        raise invalid_bbox("bbox extends outside the analyzed image.")
    if width < settings.min_review_bbox_width or height < settings.min_review_bbox_height:
        raise invalid_bbox(
            f"bbox is smaller than the minimum {settings.min_review_bbox_width}x{settings.min_review_bbox_height}."
        )
    image_area = context.image_width * context.image_height
    if image_area > 0 and (width * height) > image_area * settings.max_review_bbox_area_ratio:
        raise invalid_bbox(f"bbox covers more than {settings.max_review_bbox_area_ratio:.0%} of the image.")

    return BoundingBox(x=x, y=y, width=width, height=height)


def process_review(
    pipeline: Pipeline,
    context: ReviewContext,
    items: list[ReviewItemRequest],
    settings: ApiSettings,
    image_width: int,
    image_height: int,
    input_path: str,
    image: Image,
    output_image_path: str,
    report_path: str,
    log_path: str,
    processing_id: str,
) -> ReviewOutcome:
    if image_width != context.image_width or image_height != context.image_height:
        raise invalid_review("The uploaded image does not match the image this review token was issued for.")

    token_by_id = {d.detection_id: d for d in context.detections}
    events: list[dict] = []

    # --- Resolve ACCEPT/REJECT intents against the TRUSTED token, never
    # against anything else the request claims about a detection. -------
    decisions: dict[str, ReviewItemRequest] = {}
    manual_items: list[ReviewItemRequest] = []
    for item in items:
        if item.detection_id is not None:
            if item.detection_id not in token_by_id:
                raise unknown_detection(f"Unknown detection_id: {item.detection_id!r}")
            if item.review_status is None:
                raise invalid_review("A detection_id item requires review_status.")
            if item.review_status == "REJECTED":
                reason = item.reason or ""
                if len(reason) > settings.max_review_reason_length:
                    raise invalid_review(
                        f"reason exceeds the {settings.max_review_reason_length}-character limit."
                    )
            decisions[item.detection_id] = item
            events.append({"event": item.review_status, "detection_id": item.detection_id, "source": "HUMAN"})
        elif item.source == "MANUAL":
            manual_items.append(item)
        else:
            raise invalid_review("Each review item must have either detection_id or source=\"MANUAL\".")

    # --- Rebuild the trusted "kept" detections (§16 fail-safe). ---------
    kept_detections: list[Detection] = []
    kept_ids: list[str] = []
    critical_rejection_occurred = False

    for token_detection in context.detections:
        decision = decisions.get(token_detection.detection_id)
        review_status = decision.review_status if decision else "PENDING"

        if review_status == "REJECTED" and token_detection.type not in INTRINSIC_CRITICAL_TYPES:
            # Non-critical false-positive correction: honored, dropped
            # entirely from redaction.
            continue

        needs_review = token_detection.needs_review
        if review_status == "REJECTED":
            # §16/§20: rejecting a CRITICAL finding never removes the mask
            # and never implies "safe" — it stays in the redaction set and
            # is flagged for a human supervisor to look at again.
            critical_rejection_occurred = True
            needs_review = True
        elif review_status == "ACCEPTED":
            # A human explicitly confirmed this finding — safe to clear a
            # PENDING uncertainty flag; the redaction action is unchanged
            # either way (this never affects what gets masked).
            needs_review = False

        kept_detections.append(
            Detection(
                type=token_detection.type,
                text="",  # never round-tripped through the token — see module docstring
                confidence=token_detection.confidence,
                bounding_box=BoundingBox(
                    x=token_detection.x, y=token_detection.y,
                    width=token_detection.width, height=token_detection.height,
                ),
                risk_score=0.0,  # not consulted downstream of a decision already made (see review_service module notes)
                risk_level=RiskLevel(token_detection.risk_level),
                action=RedactionAction(token_detection.action),
                source_layers=["review_kept"],
                unknown=False,
                needs_review=needs_review,
            )
        )
        kept_ids.append(token_detection.detection_id)

    # --- Validate + score MANUAL additions via the REAL Core engines. ---
    manual_detections: list[Detection] = []
    manual_object_ids: dict[int, str] = {}
    for item in manual_items:
        if item.type not in REVIEWABLE_MANUAL_TYPES:
            raise invalid_detection_type(f"Unsupported manual detection type: {item.type!r}")
        bbox = _validate_manual_bbox(item, context, settings)

        # §15: never represent the same sensitive region twice — skip a
        # manual box that overlaps an existing kept detection of the same
        # type rather than creating a duplicate finding.
        if any(kd.type == item.type and _boxes_overlap(kd.bounding_box, bbox) for kd in kept_detections):
            events.append({"event": "MANUAL_SKIPPED_REDUNDANT", "detection_id": None, "source": "HUMAN"})
            continue

        detection = Detection(
            type=item.type,
            text="",
            confidence=_MANUAL_DETECTION_CONFIDENCE,
            bounding_box=bbox,
            source_layers=["manual_review"],
            unknown=False,
        )
        manual_id = str(uuid.uuid4())
        manual_object_ids[id(detection)] = manual_id
        manual_detections.append(detection)
        events.append({"event": "MANUAL_ADDED", "detection_id": manual_id, "source": "HUMAN"})

    if manual_detections:
        # The exact same RiskEngine/PolicyEngine instances Pipeline.process()
        # itself uses — never a new instance, never reimplemented logic.
        pipeline.risk_engine.score(manual_detections, [])
        manual_detections = pipeline.policy_engine.decide(manual_detections)  # filters action==NONE, mutates in place

    manual_ids = [manual_object_ids[id(d)] for d in manual_detections]

    final_detections = kept_detections + manual_detections
    detection_ids = kept_ids + manual_ids

    result = pipeline.redact_verify_and_finalize(
        processing_id, input_path, image, final_detections, output_image_path, report_path, log_path
    )

    if critical_rejection_occurred and not result.verification.needs_human_review:
        updated_verification = replace(result.verification, needs_human_review=True)
        result = replace(result, verification=updated_verification)
        result.report["verification"]["needs_human_review"] = True

    events.append({"event": "COMPLETED" if not result.blocked else "FAILED", "detection_id": None, "source": "SYSTEM"})

    return ReviewOutcome(
        process_result=result,
        detection_ids=detection_ids,
        critical_rejection_occurred=critical_rejection_occurred,
        events=events,
    )
