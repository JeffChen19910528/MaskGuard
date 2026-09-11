"""Application-level Core service (Phase 8.1 §20). Built ONCE per running
application (see `dependencies.py`'s cached singleton) rather than once per
request, so OCR engine construction happens on startup, not on every HTTP
call — the point that matters most once a future engine (PaddleOCR, Local
AI) has real model-loading cost (Phase 7 report's "cold start" finding).

Every method here does exactly two things: manage a secure temp-file
lifecycle around Core's file-path-based interface (§14), and call straight
into the ONE shared `Pipeline`/`WholeImageSanityScanner` instance. No
Detection/Risk/Policy/Redaction/Verification/OCR/normalization/
canonicalization logic is written here — see `mapping.py` for the (also
logic-free) Core-result -> API-schema conversion.
"""
from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config, load_config
from ..pipeline import Pipeline, ProcessResult
from ..preprocessing import load_and_normalize
from ..verification.whole_image_sanity import SanityScanResult
from .concurrency import ConcurrencyLimiter
from .config import ApiSettings
from .review_service import ReviewOutcome, process_review
from .review_token import ReplayStore, ReviewTokenIssuer, TokenDetection
from .schemas import ReviewItemRequest


@dataclass
class RedactResult:
    process_result: ProcessResult
    image_bytes: bytes | None  # None when Strict Mode blocked output (§40)


class MaskGuardService:
    def __init__(
        self,
        config: Config | None = None,
        user_rules_path: str | None = None,
        review_token_ttl_seconds: int = 600,
        max_concurrent_jobs: int = 4,
        review_token_secret: str | None = None,
        replay_store: ReplayStore | None = None,
    ) -> None:
        self.config = config or load_config()
        self.pipeline = Pipeline(self.config, user_rules_path=user_rules_path)
        # One signing secret + replay guard per running process (Phase 8.3
        # §31/§33) — shared across all requests via this one service
        # instance (§20), never persisted. `review_token_secret` (Phase 9
        # §16) lets a deployment supply its own value (e.g. from a Docker
        # secret file); `None` auto-generates one at process start, exactly
        # as Phase 8.3/8.4 already did — production mode refuses to start
        # with an auto-generated secret (see config.validate_production_secret,
        # called before this constructor ever runs — app.py).
        self.review_token_issuer = ReviewTokenIssuer(
            ttl_seconds=review_token_ttl_seconds,
            secret=review_token_secret.encode("utf-8") if review_token_secret else None,
            # Phase 10.6 §21: `None` -> the issuer's own default
            # (`InMemoryReplayStore`, unchanged single-instance behavior).
            # A Redis-backed store is injected by `dependencies.py` only
            # when `REDIS_ENABLED=true`.
            replay_store=replay_store,
        )
        # One bounded-concurrency gate for the ONE shared Pipeline (Phase
        # 8.4 §21/§22) — never a second Pipeline/OCR engine instance.
        self.concurrency_limiter = ConcurrencyLimiter(max_concurrent_jobs)

    @staticmethod
    def build_token_detections(result: ProcessResult, detection_ids: list[str]) -> list[TokenDetection]:
        """Converts `result.report["detections"]` (already-excludes-raw-text,
        see report_builder.py) into signed-token entries (Phase 8.3 §6/§30).
        `detection_ids` must be the same length/order — see routes/images.py."""
        return [
            TokenDetection(
                detection_id=detection_id,
                type=d["type"],
                risk_level=d["risk"],
                action=d["action"],
                confidence=d["confidence"],
                needs_review=d["needs_review"],
                x=d["region"][0], y=d["region"][1], width=d["region"][2], height=d["region"][3],
            )
            for d, detection_id in zip(result.report["detections"], detection_ids, strict=True)
        ]

    @property
    def ocr_engine_available(self) -> bool:
        # Construction-time readiness signal only — does NOT run OCR
        # (health checks must never process an image, §6).
        return self.pipeline.ocr_engine is not None

    def _run_pipeline(self, image_bytes: bytes, suffix: str) -> tuple[ProcessResult, bytes | None]:
        # NOTE: returns the output bytes rather than stashing them on
        # `self` — this service is one shared instance app-wide (§20), so
        # per-request state must never live on `self`/be mutated here.
        with tempfile.TemporaryDirectory(prefix="maskguard_api_") as tmp:
            tmp_dir = Path(tmp)
            input_path = tmp_dir / f"input{suffix}"  # fixed name — never the client's filename (§14)
            output_path = tmp_dir / "output.png"
            report_path = tmp_dir / "report.json"
            log_path = tmp_dir / "audit.log"

            input_path.write_bytes(image_bytes)
            result = self.pipeline.process(str(input_path), str(output_path), str(report_path), str(log_path))
            # Read the redacted image bytes back out BEFORE the `with` block
            # exits and the temp directory (and everything in it) is
            # removed — cleanup happens on every exit path, including an
            # exception above, via the context manager.
            output_bytes = Path(result.output_path).read_bytes() if result.output_path else None
            return result, output_bytes

    def analyze(self, image_bytes: bytes, suffix: str) -> ProcessResult:
        """Full Core pipeline (OCR -> Detection -> Risk -> Policy ->
        Redaction -> Verification -> Sanity Scan). The redacted image is
        produced (Verification needs it to exist to re-check) but discarded
        here — `/analyze` returns findings only, never image bytes (§7/§8).
        """
        result, _ = self._run_pipeline(image_bytes, suffix)
        return result

    def redact(self, image_bytes: bytes, suffix: str) -> RedactResult:
        """Same full Core pipeline as `analyze()` — deliberately the exact
        same call, not a second implementation — but also returns the
        redacted image bytes (§9)."""
        result, output_bytes = self._run_pipeline(image_bytes, suffix)
        return RedactResult(process_result=result, image_bytes=output_bytes)

    def verify(self, image_bytes: bytes, suffix: str) -> SanityScanResult:
        """Independent, detection-context-free check via the SAME
        `WholeImageSanityScanner` instance `Pipeline.process()` itself uses
        as its post-redaction safety net (Skill.md Phase 6.1 P0-2) —
        deliberately NOT `VerificationEngine.verify_and_fix()`, which
        requires a prior `Detection` list and MUTATES redaction via
        `.escalate()`. A standalone "does this image still contain
        recoverable sensitive data" check has no such prior context, so the
        Core capability that already matches that shape is the sanity
        scanner, not Verification (§10's "沿用現有 interface" applied
        literally: don't force-fit a different Core method)."""
        with tempfile.TemporaryDirectory(prefix="maskguard_api_") as tmp:
            tmp_dir = Path(tmp)
            input_path = tmp_dir / f"input{suffix}"
            input_path.write_bytes(image_bytes)
            image = load_and_normalize(str(input_path))
            return self.pipeline.sanity_scanner.scan(image, self.config.ocr.language)

    def review(
        self,
        image_bytes: bytes,
        suffix: str,
        review_token: str,
        items: list[ReviewItemRequest],
        settings: ApiSettings,
        image_width: int,
        image_height: int,
        identity_key: str | None = None,
    ) -> tuple[ReviewOutcome, bytes | None]:
        """Human Review submission (Phase 8.3). Decodes/verifies the signed
        review token (review_token.py — raises `ReviewTokenError` on a bad/
        expired/replayed token, never silently accepted), reconstructs a
        trusted `Detection` list, and runs the exact same
        `Pipeline.redact_verify_and_finalize()` tail `/redact` uses — see
        review_service.py for the actual reconstruction/validation logic,
        which is NOT written here. `identity_key` (Phase 10.3 §25-27): the
        submitting caller's `issuer|subject`, checked against the token's
        own binding — `None` when OIDC is disabled, a no-op in that case."""
        context = self.review_token_issuer.verify_and_consume(review_token, identity_key=identity_key)

        with tempfile.TemporaryDirectory(prefix="maskguard_api_") as tmp:
            tmp_dir = Path(tmp)
            input_path = tmp_dir / f"input{suffix}"
            output_path = tmp_dir / "output.png"
            report_path = tmp_dir / "report.json"
            log_path = tmp_dir / "audit.log"

            input_path.write_bytes(image_bytes)
            image = load_and_normalize(str(input_path))
            processing_id = f"{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8]}"

            outcome = process_review(
                self.pipeline, context, items, settings, image_width, image_height,
                str(input_path), image, str(output_path), str(report_path), str(log_path), processing_id,
            )
            # Same "read bytes before the temp dir disappears" pattern as
            # `_run_pipeline` — see its comment for why.
            output_bytes = (
                Path(outcome.process_result.output_path).read_bytes() if outcome.process_result.output_path else None
            )
            return outcome, output_bytes
