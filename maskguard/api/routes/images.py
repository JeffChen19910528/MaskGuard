"""POST /api/v1/analyze, /redact, /verify, /process (Phase 8.1 §5/§7-11).

Every handler: (1) receives the upload, (2) validates it, (3) calls
`MaskGuardService` — i.e. Core — (4) maps the Core result to an API schema,
(5) returns it. No Detection/Risk/Policy/Redaction/Verification/OCR logic
is written in this file.

Route functions are `async def` and offload the CPU-bound Core call to a
worker thread via `anyio.to_thread.run_sync` (Phase 8.1 §21: Tesseract/
OpenCV/Pillow calls are synchronous and must not block the event loop),
wrapped in `asyncio.wait_for` for the configurable processing timeout
(§13). This is NOT a job queue — one request, one worker-thread call, no
persisted job state (§30).
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from ..audit import event_types as audit_event_types
from ..audit import service as audit_service
from ..audit.models import RESULT_FAILURE, RESULT_SUCCESS
from ..auth.models import AuthenticatedIdentity
from ..authorization.dependencies import require_permission
from ..authorization.permissions import IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY
from ..config import ApiSettings, get_settings
from ..dependencies import get_service
from ..mapping import to_analyze_response, to_verify_response
from ..ratelimit.config import IMAGE_ANALYZE as RL_IMAGE_ANALYZE
from ..ratelimit.config import IMAGE_REDACT as RL_IMAGE_REDACT
from ..ratelimit.config import IMAGE_VERIFY as RL_IMAGE_VERIFY
from ..ratelimit.dependencies import require_rate_limit
from ..schemas import AnalyzeResponse, VerifyResponse
from ..service import MaskGuardService
from ..validation import ValidatedUpload, validate_upload
from ._shared import log_request, run_with_timeout

router = APIRouter()


def _emit_image_event(
    event_type: str, operation: str, request: Request, identity: AuthenticatedIdentity | None, *,
    resource_id: str | None, result: str, metadata: dict,
) -> None:
    """Phase 10.4 §12/§13: counts and status only — never detection
    VALUES, OCR text, or image bytes (see each call site's own comment
    for why the specific metadata chosen there is safe)."""
    audit_service.emit(
        event_type,
        actor_type="user" if identity is not None else "anonymous",
        actor_id=identity.identity_key if identity is not None else None,
        issuer=identity.issuer if identity is not None else None,
        request_id=getattr(request.state, "request_id", None),
        operation=operation,
        resource_type="image", resource_id=resource_id, result=result, metadata=metadata,
    )


async def _read_and_validate(file: UploadFile, settings: ApiSettings) -> tuple[bytes, ValidatedUpload]:
    # Read at most one byte beyond the limit so a huge upload is rejected
    # without buffering the whole thing in memory first.
    data = await file.read(settings.max_upload_size_bytes + 1)
    validated = validate_upload(data, settings)
    return data, validated


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: Request,
    file: UploadFile,
    service: MaskGuardService = Depends(get_service),
    settings: ApiSettings = Depends(get_settings),
    # Phase 10.5 §2/§17/§23: rate limit BEFORE authorization, and (since
    # it never calls `run_with_timeout`) always before a concurrency slot
    # is acquired — declared first so FastAPI resolves it first.
    _rate_limited: None = Depends(require_rate_limit(RL_IMAGE_ANALYZE)),
    _identity: AuthenticatedIdentity | None = Depends(require_permission(IMAGE_ANALYZE)),
) -> AnalyzeResponse:
    data, validated = await _read_and_validate(file, settings)
    t0 = time.perf_counter()
    result = await run_with_timeout(
        service.analyze, data, validated.suffix, settings=settings, limiter=service.concurrency_limiter,
    )

    # Phase 8.3 §6/§30: a fresh detection_id per finding, and a signed
    # review token minted over exactly this trusted detection list — see
    # review_token.py. Both are generated here (not in mapping.py) so the
    # SAME ids used to mint the token are the ones shown to the client.
    detection_ids = [str(uuid.uuid4()) for _ in result.report["detections"]]
    token_detections = service.build_token_detections(result, detection_ids)
    # Phase 10.3 §25-27: bind the token to the CALLING identity when one
    # exists (`_identity` is None whenever OIDC is disabled — see
    # `require_permission`'s own docstring — so this is a no-op then,
    # exactly preserving Phase 8.3/9 behavior).
    identity_key = _identity.identity_key if _identity is not None else None
    review_token = service.review_token_issuer.issue(
        token_detections, validated.width, validated.height, identity_key=identity_key
    )

    response = to_analyze_response(result, detection_ids, review_token=review_token)
    log_request(
        request, "analyze", duration_s=time.perf_counter() - t0, file_size=len(data),
        detection_count=len(response.detections), status=response.status,
    )
    # Phase 10.4 §12/§13: counts, never detection values (Detection.text
    # never reaches this layer to begin with — see mapping.py). §13:
    # `critical_detection_count` judged safe (a count, not a value) —
    # same reasoning already applied to Phase 8's own report/audit design.
    critical_count = sum(1 for d in result.report["detections"] if d.get("risk") == "CRITICAL")
    _emit_image_event(
        audit_event_types.IMAGE_ANALYZE, "image.analyze", request, _identity,
        resource_id=result.processing_id, result=RESULT_SUCCESS,
        metadata={
            "detection_count": len(response.detections), "critical_detection_count": critical_count,
            "blocked": result.blocked,
        },
    )
    return response


@router.post("/redact")
async def redact(
    request: Request,
    file: UploadFile,
    service: MaskGuardService = Depends(get_service),
    settings: ApiSettings = Depends(get_settings),
    _rate_limited: None = Depends(require_rate_limit(RL_IMAGE_REDACT)),
    _identity: AuthenticatedIdentity | None = Depends(require_permission(IMAGE_REDACT)),
) -> Response:
    data, validated = await _read_and_validate(file, settings)
    t0 = time.perf_counter()
    redact_result = await run_with_timeout(
        service.redact, data, validated.suffix, settings=settings, limiter=service.concurrency_limiter,
    )
    log_request(
        request, "redact", duration_s=time.perf_counter() - t0, file_size=len(data),
        blocked=redact_result.process_result.blocked,
        status=redact_result.process_result.verification.status,
    )
    _emit_image_event(
        audit_event_types.IMAGE_REDACT, "image.redact", request, _identity,
        resource_id=redact_result.process_result.processing_id,
        result=RESULT_FAILURE if redact_result.process_result.blocked else RESULT_SUCCESS,
        metadata={
            "verification_status": redact_result.process_result.verification.status,
            "needs_human_review": redact_result.process_result.verification.needs_human_review,
            "blocked": redact_result.process_result.blocked,
        },
    )
    if redact_result.image_bytes is None:
        # Strict Mode withheld the output (Skill.md §40) — not an error, a
        # valid security outcome. Surface it as a normal 200 JSON status
        # rather than pretending an image exists (§18: MaskGuard status !=
        # HTTP status, but there is genuinely no image to return here).
        return JSONResponse(
            status_code=200,
            content={
                "status": "BLOCKED",
                "message": "Strict Mode verification failed; output was withheld (Skill.md §40).",
                "verification": {
                    "status": redact_result.process_result.verification.status,
                    "needs_human_review": redact_result.process_result.verification.needs_human_review,
                },
            },
        )
    return Response(content=redact_result.image_bytes, media_type="image/png")


@router.post("/verify", response_model=VerifyResponse)
async def verify(
    request: Request,
    file: UploadFile,
    service: MaskGuardService = Depends(get_service),
    settings: ApiSettings = Depends(get_settings),
    _rate_limited: None = Depends(require_rate_limit(RL_IMAGE_VERIFY)),
    _identity: AuthenticatedIdentity | None = Depends(require_permission(IMAGE_VERIFY)),
) -> VerifyResponse:
    data, validated = await _read_and_validate(file, settings)
    t0 = time.perf_counter()
    scan = await run_with_timeout(
        service.verify, data, validated.suffix, settings=settings, limiter=service.concurrency_limiter,
    )
    response = to_verify_response(scan)
    log_request(
        request, "verify", duration_s=time.perf_counter() - t0, file_size=len(data), clean=response.clean,
    )
    _emit_image_event(
        audit_event_types.IMAGE_VERIFY, "image.verify", request, _identity,
        resource_id=None,  # a standalone /verify call has no processing_id — no Pipeline.process() run
        result=RESULT_SUCCESS if response.clean else RESULT_FAILURE,
        metadata={"clean": response.clean, "found_type_count": len(response.found_types)},
    )
    return response


@router.post("/process", response_model=AnalyzeResponse)
async def process(
    request: Request,
    file: UploadFile,
    service: MaskGuardService = Depends(get_service),
    settings: ApiSettings = Depends(get_settings),
    # Phase 10.3 §21: `/process` is an ALIAS of `/analyze` — its own route
    # declares the SAME `require_permission(IMAGE_ANALYZE)` dependency
    # (based on actual operation semantics, not the route name) rather
    # than relying on the inner `analyze()` call to enforce it, because
    # FastAPI only evaluates a dependency list for the ROUTE HANDLER
    # actually invoked for a given HTTP path — calling `analyze()` as a
    # plain Python function below does NOT re-run its dependency list.
    # Phase 10.5: same reasoning applies to rate limiting — `/process`
    # declares its OWN `require_rate_limit(IMAGE_ANALYZE)` dependency.
    _rate_limited: None = Depends(require_rate_limit(RL_IMAGE_ANALYZE)),
    _identity: AuthenticatedIdentity | None = Depends(require_permission(IMAGE_ANALYZE)),
) -> AnalyzeResponse:
    """Unified endpoint (§11): identical to `/analyze` — both call the same
    full `Pipeline.process()` and return the same findings-only JSON shape.
    Kept as a separate route because `/analyze` and `/process` communicate
    different INTENT to a client (detect-only vs. run-the-pipeline), not
    different behavior; use `/redact` for image bytes."""
    return await analyze(request, file, service, settings, _rate_limited, _identity)
