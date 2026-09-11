"""Unified API error handling (Phase 8.1 §17). Every error response has the
same shape:

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

and NEVER a Python traceback, filesystem path, module path, dependency
version, or environment variable — those are logged server-side (via
`logging`, request-id-tagged) but never sent to the client.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("maskguard.api")


class ApiError(Exception):
    """Base class for API errors with a stable machine-readable `code`."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(
        self, message: str, *, code: str | None = None, status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        # Phase 10.5 §25: lets a specific error (e.g. rate limiting's
        # `Retry-After`) attach a small, safe response header without
        # every other `ApiError` subclass needing to know about it.
        self.headers = headers or {}


class InvalidImageError(ApiError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "INVALID_IMAGE"


class FileTooLargeError(ApiError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "FILE_TOO_LARGE"


class ImageDimensionsError(ApiError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "IMAGE_DIMENSIONS_INVALID"


class ProcessingTimeoutError(ApiError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "PROCESSING_TIMEOUT"


# --- Phase 8.3: Human Review --------------------------------------------
# INVALID_REVIEW / UNKNOWN_DETECTION / INVALID_BBOX / INVALID_DETECTION_TYPE
# are malformed-or-invalid-CONTENT errors (schema was fine, the meaning
# wasn't) — 422, the same class ImageDimensionsError already uses.
# REVIEW_EXPIRED / REVIEW_CONFLICT are about the review CONTEXT'S state
# (too old / already used) rather than this request's content — 409.


class ReviewExpiredError(ApiError):
    status_code = status.HTTP_409_CONFLICT
    code = "REVIEW_EXPIRED"


class ReviewConflictError(ApiError):
    status_code = status.HTTP_409_CONFLICT
    code = "REVIEW_CONFLICT"


# --- Phase 8.4: API Security Hardening ----------------------------------


class TooManyConcurrentJobsError(ApiError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "TOO_MANY_CONCURRENT_JOBS"


class TooManyReviewItemsError(ApiError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "TOO_MANY_REVIEW_ITEMS"


def _error_body(code: str, message: str, request_id: str | None) -> dict:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        request_id = _request_id_of(request)
        logger.info("api_error code=%s status=%s request_id=%s", exc.code, exc.status_code, request_id)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, request_id),
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = _request_id_of(request)
        logger.info("validation_error request_id=%s", request_id)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_error_body("VALIDATION_ERROR", "Request did not match the expected schema.", request_id),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _request_id_of(request)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("HTTP_ERROR", str(exc.detail), request_id),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id_of(request)
        # Full exception (type, message, traceback) goes to the SERVER log
        # only — never to the client response. `exc_info=True` is safe here
        # because MaskGuard's own exceptions never carry raw OCR/detection
        # text (Detection.text never reaches this layer — see routes/images.py).
        logger.exception("unhandled_error request_id=%s", request_id)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body("INTERNAL_ERROR", "An unexpected error occurred.", request_id),
        )
