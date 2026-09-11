"""API-layer configuration (Phase 8.1 §13). Deliberately separate from
`maskguard.config.Config` — that is Core PIPELINE behavior (OCR/detection/
masking/output); this is HTTP-REQUEST-HANDLING limits (upload size, image
dimensions, CORS, timeout). Neither one configures the other.

All limits are centralized here — no numeric literal for a security limit
should appear directly in a route handler. Values are conservative defaults,
overridable via environment variables (documented in README.md), never
hardcoded scattered across `routes/`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _secret_env(file_var: str, value_var: str) -> str | None:
    """Phase 9 §16: prefer a Docker-secret-style `*_FILE` path (the
    recommended production mechanism — see docker-compose.prod.yml's
    `secrets:` block, which mounts the operator-supplied secret at
    `/run/secrets/review_token_secret`, never in the process environment
    directly) over the plain env var, so a deployment can use either without
    a code change. Trailing newlines from `echo`/file editors are stripped;
    an empty file is treated the same as "not set" (falls through to
    `validate_production_secret`'s missing-secret error in production)."""
    file_path = os.environ.get(file_var)
    if file_path:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
            if content:
                return content
        except OSError:
            pass
    return os.environ.get(value_var)


def _origins_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


#: Phase 9 §17: obviously-insecure placeholder values a careless operator
#: might paste into a production `.env` — rejected outright, never treated
#: as "a secret was provided."
_INSECURE_SECRET_VALUES = frozenset(
    {"changeme", "change-me", "change_me", "default", "default-secret", "secret",
     "password", "test", "testing", "insecure", "example", "xxxxxxxx"}
)
#: Minimum length a production secret must meet (a coarse strength floor —
#: this is NOT entropy analysis, just enough to catch "abc123"-class mistakes).
_MIN_PRODUCTION_SECRET_LENGTH = 32


class InsecureProductionConfigError(RuntimeError):
    """Raised at startup (never mid-request) when running in production
    mode with a missing or obviously-insecure required secret (§17) — the
    app must fail closed, not start with a weak/absent secret."""


def validate_production_secret(environment: str, raw_secret: str | None) -> None:
    if environment != "production":
        return  # development/test: an unset secret just means "auto-generate" (unchanged Phase 8.3/8.4 behavior)
    if raw_secret is None or not raw_secret.strip():
        raise InsecureProductionConfigError(
            "MASKGUARD_ENV=production requires MASKGUARD_REVIEW_TOKEN_SECRET to be set "
            "(e.g. via a Docker secret file) — refusing to start with an auto-generated, "
            "unobservable, non-operator-controlled secret in production."
        )
    if raw_secret.strip().lower() in _INSECURE_SECRET_VALUES:
        raise InsecureProductionConfigError(
            "MASKGUARD_REVIEW_TOKEN_SECRET is an obviously-insecure placeholder value — "
            "set a real, randomly-generated secret before running in production."
        )
    if len(raw_secret) < _MIN_PRODUCTION_SECRET_LENGTH:
        raise InsecureProductionConfigError(
            f"MASKGUARD_REVIEW_TOKEN_SECRET is shorter than the required "
            f"{_MIN_PRODUCTION_SECRET_LENGTH} characters for production use."
        )


@dataclass(frozen=True)
class ApiSettings:
    #: Reject an upload before decoding anything past this many bytes (§13).
    max_upload_size_bytes: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024))
    max_image_width: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_IMAGE_WIDTH", 8000))
    max_image_height: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_IMAGE_HEIGHT", 8000))
    max_image_pixels: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_IMAGE_PIXELS", 40_000_000))
    #: Soft wall-clock budget for one request's Core processing (§13/§21).
    #: The underlying worker thread is NOT force-killed if this elapses
    #: (Phase 8.1 deliberately ships no job-queue/cancellation infra — see
    #: README "Known limitations") — the client just gets a 504 instead of
    #: hanging forever.
    processing_timeout_seconds: int = field(default_factory=lambda: _int_env("MASKGUARD_PROCESSING_TIMEOUT_SECONDS", 60))
    #: Empty by default — Phase 8.2's frontend origin gets added explicitly
    #: when it exists (§19). Never `["*"]` by default.
    cors_allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: _origins_env("MASKGUARD_CORS_ALLOWED_ORIGINS", ())
    )

    # --- Phase 8.3: Human Review ------------------------------------------
    #: How long a `/analyze` response's signed review token stays valid
    #: (§32). An expired token is refused with REVIEW_EXPIRED — never
    #: processed.
    review_token_ttl_seconds: int = field(default_factory=lambda: _int_env("MASKGUARD_REVIEW_TOKEN_TTL_SECONDS", 600))
    #: Reason text on a REJECTED item, bounded (§9) — never unbounded free
    #: text stored/logged.
    max_review_reason_length: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_REVIEW_REASON_LENGTH", 200))
    #: A manually-drawn box smaller than this in either dimension is
    #: rejected as too small to be a meaningful redaction target (§14).
    min_review_bbox_width: int = field(default_factory=lambda: _int_env("MASKGUARD_MIN_REVIEW_BBOX_WIDTH", 4))
    min_review_bbox_height: int = field(default_factory=lambda: _int_env("MASKGUARD_MIN_REVIEW_BBOX_HEIGHT", 4))
    #: A manual box may never cover more than this fraction of the total
    #: image area (§14) — guards against a huge/accidental selection.
    max_review_bbox_area_ratio: float = field(
        default_factory=lambda: float(os.environ.get("MASKGUARD_MAX_REVIEW_BBOX_AREA_RATIO", "0.9"))
    )

    # --- Phase 8.4: API Security Hardening --------------------------------
    #: Outer ASGI-level ceiling on the WHOLE request body (middleware.py) —
    #: a little above `max_upload_size_bytes` to allow multipart boundary/
    #: header/`review`-field overhead; `max_upload_size_bytes` remains the
    #: precise, authoritative per-FILE limit.
    max_request_body_bytes: int = field(
        default_factory=lambda: _int_env("MASKGUARD_MAX_REQUEST_BODY_BYTES", 12 * 1024 * 1024)
    )
    #: Total review items (`ACCEPTED`/`REJECTED`/`MANUAL`) one `/review`
    #: submission may contain — bounds per-item validation work.
    max_review_items: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_REVIEW_ITEMS", 200))
    #: Of those, how many may be brand-new MANUAL detections — the
    #: RiskEngine/PolicyEngine-scoring-triggering subset (§15), bounded
    #: tighter than the total since each one does real Core work.
    max_manual_detections: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_MANUAL_DETECTIONS", 50))
    #: Raw byte size of the `review` multipart form field (the JSON string)
    #: before it is even parsed — rejects a pathologically large payload
    #: without handing it to `json.loads`/Pydantic first.
    max_review_payload_bytes: int = field(
        default_factory=lambda: _int_env("MASKGUARD_MAX_REVIEW_PAYLOAD_BYTES", 256 * 1024)
    )
    #: A `review_token` string longer than this is rejected before any
    #: base64/HMAC work is done on it (§17 — bounds attacker-controlled
    #: token size, defense in depth alongside `max_review_items` already
    #: bounding what a LEGITIMATE token can grow to).
    max_review_token_bytes: int = field(
        default_factory=lambda: _int_env("MASKGUARD_MAX_REVIEW_TOKEN_BYTES", 64 * 1024)
    )
    #: Bounded concurrent CPU-heavy Core jobs (analyze/redact/verify/review)
    #: this process will run at once (§21/§22) — one shared `Pipeline`/OCR
    #: engine instance throughout, never one per request. A request that
    #: would exceed this is refused immediately with `429`, never queued
    #: indefinitely.
    max_concurrent_jobs: int = field(default_factory=lambda: _int_env("MASKGUARD_MAX_CONCURRENT_JOBS", 4))

    # --- Phase 9: Deployment -----------------------------------------------
    #: `"development"` (default) or `"production"` — gates the fail-closed
    #: secret check below. Never inferred from anything but this explicit
    #: variable (no "guess production from hostname" magic).
    environment: str = field(
        default_factory=lambda: os.environ.get("MASKGUARD_ENV", "development").strip().lower()
    )
    #: Raw operator-supplied secret (Phase 9 §16) — `None` in development
    #: means "auto-generate one at process start" (Phase 8.3/8.4 behavior,
    #: unchanged). In production this MUST be set — see
    #: `validate_production_secret()`, called at app startup (app.py).
    review_token_secret: str | None = field(
        default_factory=lambda: _secret_env("MASKGUARD_REVIEW_TOKEN_SECRET_FILE", "MASKGUARD_REVIEW_TOKEN_SECRET")
    )


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()
