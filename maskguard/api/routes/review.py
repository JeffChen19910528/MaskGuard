"""POST /api/v1/review (Phase 8.3 §17-19).

Response shape: this endpoint returns the FINAL REDACTED IMAGE
(`image/png`), the same contract `/redact` already uses — §25 requires the
frontend to display the actual backend-produced redacted image after
review, and MaskGuard's API is stateless (no image storage a second
"fetch the result" call could read from — Phase 8.1 §30 unchanged), so
returning it in the same response as the outcome avoids inventing
persistence just to split those into two calls. The JSON "final result"
shape §19 describes (status/needs_human_review/blocked/detections/
verification/summary) is still fully computed — it rides along as response
headers (`X-Review-*`) rather than duplicating `/analyze`'s JSON-body
contract on top of a binary body. A blocked (Strict Mode) outcome returns
`200` JSON with `status: "BLOCKED"`, identical to `/redact`'s own pattern
— never a fake image.

Every validation step below (§12/§30/§31) is real: `detection_id`s, types,
risk, action, and confidence for EXISTING detections are resolved from the
signed review token (review_token.py) — never from this request body. Only
a brand-new MANUAL detection's `type`/`bbox` come from the client, and even
those are scored by the real RiskEngine/PolicyEngine before anything is
redacted (review_service.py). No Detection/Risk/Policy/Redaction/
Verification ALGORITHM is written in this file.
"""
from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from ..audit import event_types as audit_event_types
from ..audit import service as audit_service
from ..audit.models import RESULT_SUCCESS
from ..authorization.dependencies import AuthorizationContext, get_authorization_context
from ..authorization.permissions import REVIEW_ACCEPT, REVIEW_MANUAL_DETECT, REVIEW_REJECT
from ..config import ApiSettings, get_settings
from ..dependencies import get_service
from ..errors import ReviewConflictError, ReviewExpiredError, TooManyReviewItemsError
from ..ratelimit.config import REVIEW as RL_REVIEW
from ..ratelimit.dependencies import require_rate_limit
from ..redisstate.errors import DependencyUnavailableError
from ..review_service import ReviewValidationError
from ..review_token import ReplayStoreUnavailableError, ReviewTokenError
from ..schemas import ReviewSubmissionRequest
from ..service import MaskGuardService
from ..validation import validate_upload
from ._shared import log_request, run_with_timeout

logger = logging.getLogger("maskguard.api")

router = APIRouter()

# Phase 10.4 §14/§15/§46: one durable audit event per actual review
# DECISION (accept/reject/manual-detect) — never the token, never
# OCR/detection VALUES (only the already-opaque `detection_id`, §6).
# "MANUAL_SKIPPED_REDUNDANT"/"COMPLETED"/"FAILED" are internal
# bookkeeping outcomes, not distinct reviewer decisions — not audited
# separately (§9: don't create event types with no real operation behind
# them).
_REVIEW_EVENT_MAP = {
    "ACCEPTED": audit_event_types.REVIEW_ACCEPTED,
    "REJECTED": audit_event_types.REVIEW_REJECTED,
    "MANUAL_ADDED": audit_event_types.REVIEW_MANUAL_DETECTION,
}

_TOKEN_ERROR_MAP = {
    "REVIEW_EXPIRED": ReviewExpiredError,
    "REVIEW_CONFLICT": ReviewConflictError,
}


def _parse_review_payload(review: str) -> ReviewSubmissionRequest:
    try:
        return ReviewSubmissionRequest.model_validate_json(review)
    except ValidationError:
        raise ReviewValidationError(
            "Malformed review payload — expected {\"review_token\": ..., \"items\": [...]}.",
            code="INVALID_REVIEW",
            status_code=422,
        ) from None
    except (json.JSONDecodeError, TypeError):
        raise ReviewValidationError("Review payload is not valid JSON.", code="INVALID_REVIEW", status_code=422) from None


@router.post("/review")
async def review(
    request: Request,
    file: UploadFile,
    review: str = Form(..., description="JSON-encoded ReviewSubmissionRequest"),
    service: MaskGuardService = Depends(get_service),
    settings: ApiSettings = Depends(get_settings),
    # Phase 10.5 §20/§21: identity/IP-keyed, NEVER keyed by review token
    # or detection value — runs before the token is even parsed.
    _rate_limited: None = Depends(require_rate_limit(RL_REVIEW)),
    authz: AuthorizationContext = Depends(get_authorization_context),
) -> Response:
    # Phase 8.4 §11/§17: reject a pathologically large `review` field
    # BEFORE it's handed to json.loads/Pydantic at all — cheap byte check.
    review_bytes = len(review.encode("utf-8"))
    if review_bytes > settings.max_review_payload_bytes:
        raise ReviewValidationError(
            f"Review payload exceeds the {settings.max_review_payload_bytes}-byte limit.",
            code="INVALID_REVIEW",
            status_code=422,
        )

    submission = _parse_review_payload(review)

    # Phase 10.3 §22-24: the exact permission(s) required depend on WHICH
    # decision types this submission actually contains — checked (and
    # denied, 403) BEFORE any Core work, same "authorize before expensive
    # processing" discipline as the single-permission image endpoints
    # (§56/§57). A caller without `review.reject` cannot cause a reject
    # decision even if the SAME request also contains items they ARE
    # allowed to accept — the whole submission is rejected, never
    # partially applied.
    if any(item.review_status == "ACCEPTED" for item in submission.items):
        authz.require(REVIEW_ACCEPT)
    if any(item.review_status == "REJECTED" for item in submission.items):
        authz.require(REVIEW_REJECT)
    if any(item.source == "MANUAL" for item in submission.items):
        authz.require(REVIEW_MANUAL_DETECT)

    if len(submission.review_token.encode("utf-8")) > settings.max_review_token_bytes:
        raise ReviewValidationError(
            f"Review token exceeds the {settings.max_review_token_bytes}-byte limit.",
            code="INVALID_REVIEW",
            status_code=422,
        )
    if len(submission.items) > settings.max_review_items:
        raise TooManyReviewItemsError(
            f"Review submission has {len(submission.items)} items, exceeding the "
            f"{settings.max_review_items}-item limit."
        )
    manual_count = sum(1 for item in submission.items if item.source == "MANUAL")
    if manual_count > settings.max_manual_detections:
        raise TooManyReviewItemsError(
            f"Review submission has {manual_count} manual detections, exceeding the "
            f"{settings.max_manual_detections}-item limit."
        )

    data = await file.read(settings.max_upload_size_bytes + 1)
    validated = validate_upload(data, settings)

    t0 = time.perf_counter()
    # Phase 10.3 §25-27: the SUBMITTING caller's identity (None when OIDC
    # is disabled — `authz.identity` is always None in that case, see
    # `AuthorizationContext`) — checked against the token's own binding
    # inside `verify_and_consume`, not decided here.
    identity_key = authz.identity.identity_key if authz.identity is not None else None
    try:
        outcome, image_bytes = await run_with_timeout(
            service.review,
            data, validated.suffix, submission.review_token, submission.items, settings,
            validated.width, validated.height, identity_key,
            settings=settings, limiter=service.concurrency_limiter,
        )
    except ReviewTokenError as exc:
        error_cls = _TOKEN_ERROR_MAP.get(exc.code)
        if error_cls is None:  # INVALID_REVIEW and anything unmapped
            raise ReviewValidationError(exc.message, code=exc.code, status_code=422) from exc
        raise error_cls(exc.message) from exc
    except ReplayStoreUnavailableError as exc:
        # Phase 10.6 §30/§31/§97: the replay check itself could not be
        # performed (Redis down/timeout) — NEVER treated as "token
        # unused" (that would be fail-open, §94). The review operation
        # fails safely with a dependency-failure status, distinct from
        # every token-validity error above.
        raise DependencyUnavailableError("Review submission could not be processed; please retry shortly.") from exc

    result = outcome.process_result
    log_request(
        request, "review", duration_s=time.perf_counter() - t0, file_size=len(data),
        blocked=result.blocked, status=result.verification.status,
        critical_rejection=outcome.critical_rejection_occurred,
    )
    # Review events (§28): whitelisted fields only (event/detection_id/
    # source — no reason text, no type, no bbox), server log only.
    request_id = getattr(request.state, "request_id", None)
    for evt in outcome.events:
        logger.info(
            "review_event request_id=%s event=%s detection_id=%s source=%s",
            request_id, evt["event"], evt["detection_id"], evt["source"],
        )
        audit_type = _REVIEW_EVENT_MAP.get(evt["event"])
        if audit_type is not None:
            audit_service.emit(
                audit_type,
                actor_type="user" if authz.identity is not None else "anonymous",
                actor_id=authz.identity.identity_key if authz.identity is not None else None,
                issuer=authz.identity.issuer if authz.identity is not None else None,
                request_id=request_id, operation=evt["event"].lower(),
                resource_type="detection", resource_id=evt["detection_id"], result=RESULT_SUCCESS,
            )

    status_label = "BLOCKED" if result.blocked else ("NEEDS_REVIEW" if result.verification.needs_human_review else result.verification.status)

    if image_bytes is None:
        return JSONResponse(
            status_code=200,
            content={
                "status": "BLOCKED",
                "message": "Strict Mode verification failed; output was withheld (Skill.md §40).",
                "verification": {
                    "status": result.verification.status,
                    "needs_human_review": result.verification.needs_human_review,
                },
            },
        )

    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={
            "X-Review-Status": status_label,
            "X-Review-Needs-Human-Review": str(result.verification.needs_human_review).lower(),
            "X-Review-Blocked": str(result.blocked).lower(),
            "X-Review-Detection-Count": str(len(result.report["detections"])),
        },
    )
