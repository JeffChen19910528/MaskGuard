/**
 * TypeScript mirror of maskguard/api/schemas.py (Phase 8.1). Kept in sync
 * BY HAND with the backend Pydantic models — never widen these types to
 * add fields the backend doesn't send (especially never `raw_text` /
 * `value` / `ocr_text`; the backend never sends sensitive raw values, and
 * this type model must not invite adding them client-side either).
 */

export interface BBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Matches backend `RiskLevel` (maskguard/models.py). Presentation only —
 * the frontend never computes or overrides this value. */
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

/** Matches backend `RedactionAction` (maskguard/models.py). */
export type RedactionAction = "FULL_MASK" | "BLUR" | "PIXELATE" | "PARTIAL_MASK" | "NONE";

export interface DetectionResponse {
  /** Phase 8.3 §6: server-generated UUID4, the ONLY thing a review
   * submission may reference to accept/reject this finding. Never derived
   * from OCR text. */
  detection_id: string;
  type: string;
  risk_level: RiskLevel;
  action: RedactionAction;
  confidence: number;
  needs_review: boolean;
  bbox: BBox;
}

export interface VerificationResponse {
  status: string;
  attempts: number;
  residual_count: number;
  needs_human_review: boolean;
}

export interface SummaryResponse {
  total_detections: number;
  critical_count: number;
  needs_review_count: number;
  blocked: boolean;
}

/** `status` is the backend's own derived label — see maskguard/api/mapping.py
 * `_overall_status()`. The frontend only displays it, never reinterprets it. */
export type OverallStatus = "PASSED" | "FAILED" | "SKIPPED" | "NEEDS_REVIEW" | "BLOCKED";

export interface AnalyzeResponse {
  status: OverallStatus;
  needs_human_review: boolean;
  blocked: boolean;
  detections: DetectionResponse[];
  verification: VerificationResponse;
  summary: SummaryResponse;
  /** Phase 8.3 §5/§6: signed, short-lived, opaque — pass verbatim to
   * `POST /api/v1/review`. The frontend never decodes or inspects it. */
  review_token: string | null;
}

export interface VerifyResponse {
  clean: boolean;
  found_types: string[];
  found_critical_types: string[];
}

export interface HealthResponse {
  status: string;
  api_version: string;
  app_version: string;
  ocr_engine_available: boolean;
}

export interface ErrorDetail {
  code: string;
  message: string;
  request_id: string | null;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

/** The `/redact` route returns `image/png` bytes on success, or this JSON
 * body (still HTTP 200 — see Phase 8.1 §18) when Strict Mode withheld
 * output (maskguard/api/routes/images.py `_blocked` response). */
export interface BlockedRedactResponse {
  status: "BLOCKED";
  message: string;
  verification: {
    status: string;
    needs_human_review: boolean;
  };
}

// --- Phase 8.3: Human Review ----------------------------------------------

export type ReviewStatus = "PENDING" | "ACCEPTED" | "REJECTED";

/** One line of a `POST /api/v1/review` submission — mirrors
 * `maskguard/api/schemas.py::ReviewItemRequest` exactly. Deliberately has
 * NO field for risk_level/action/confidence/type-of-an-existing-detection:
 * the backend resolves those from the signed review_token, never from this
 * request (§30/§31) — this type must never grow one. */
export type ReviewItemRequest =
  | { detection_id: string; review_status: "ACCEPTED" }
  | { detection_id: string; review_status: "REJECTED"; reason: string }
  | { type: string; bbox: BBox; source: "MANUAL" };

export interface ReviewSubmissionRequest {
  review_token: string;
  items: ReviewItemRequest[];
}

/** `POST /api/v1/review` returns `image/png` bytes with these headers on
 * success (see maskguard/api/routes/review.py) — not a JSON body, so the
 * "final result" fields ride along as headers instead. */
export interface ReviewImageHeaders {
  status: string;
  needsHumanReview: boolean;
  blocked: boolean;
  detectionCount: number;
}

/** Same shape `/redact` uses for a Strict-Mode-withheld output. */
export interface BlockedReviewResponse {
  status: "BLOCKED";
  message: string;
  verification: {
    status: string;
    needs_human_review: boolean;
  };
}
