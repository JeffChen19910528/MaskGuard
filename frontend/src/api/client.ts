/**
 * The ONE place this app calls `fetch()` against the MaskGuard backend
 * (Phase 8.1 §19: "不要 scattered fetch() calls throughout components").
 * Every function here does exactly what its name says — upload a file,
 * return the parsed backend response — and nothing else. No detection,
 * risk, policy, or redaction decision is made here; this module only
 * transports bytes and JSON to/from the API MaskGuard Core already decided.
 */
import type {
  AnalyzeResponse,
  BlockedRedactResponse,
  BlockedReviewResponse,
  ErrorResponse,
  HealthResponse,
  ReviewImageHeaders,
  ReviewItemRequest,
  VerifyResponse,
} from "./types";

// Phase 9 §6/§20: default to SAME-ORIGIN ("" -> fetch(`${""}/api/v1/...`)
// resolves against whatever origin served this page) rather than hardcoding
// a dev URL — the production build (frontend/.env.production) deliberately
// leaves VITE_API_BASE_URL unset so requests go through the same
// reverse-proxy origin the browser already loaded the page from, never a
// direct cross-origin call to the FastAPI container. Local `npm run dev`
// still overrides this via frontend/.env.development.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

/** A client-side-generated timeout, distinct from the backend's own
 * `MASKGUARD_PROCESSING_TIMEOUT_SECONDS` (Phase 8.1 §13) — set a little
 * higher so the backend's own timeout response (504) is what the user sees
 * for a genuinely slow request, not a client-side abort racing it. */
const REQUEST_TIMEOUT_MS = 70_000;

export type ApiErrorCode =
  | "INVALID_IMAGE"
  | "FILE_TOO_LARGE"
  | "IMAGE_DIMENSIONS_INVALID"
  | "PROCESSING_TIMEOUT"
  | "VALIDATION_ERROR"
  | "HTTP_ERROR"
  | "INTERNAL_ERROR"
  | "NETWORK_ERROR"
  | "CLIENT_TIMEOUT"
  // Phase 8.3
  | "INVALID_REVIEW"
  | "UNKNOWN_DETECTION"
  | "INVALID_BBOX"
  | "INVALID_DETECTION_TYPE"
  | "REVIEW_EXPIRED"
  | "REVIEW_CONFLICT";

/** Normalized error shape for every failure mode this client can hit —
 * a real backend error response, a network failure, or a client-side
 * timeout. Never carries a raw exception object or stack trace onward;
 * only a stable code + a message safe to show a user. */
export class ApiClientError extends Error {
  code: ApiErrorCode;
  status: number | null;
  requestId: string | null;

  constructor(code: ApiErrorCode, message: string, status: number | null, requestId: string | null) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

async function readErrorBody(response: Response, requestId: string | null): Promise<ApiClientError> {
  try {
    const body = (await response.json()) as ErrorResponse;
    if (body?.error?.code && body?.error?.message) {
      return new ApiClientError(
        body.error.code as ApiErrorCode,
        body.error.message,
        response.status,
        body.error.request_id ?? requestId,
      );
    }
  } catch {
    // Response body wasn't the expected JSON error shape — fall through to a generic error.
  }
  return new ApiClientError("HTTP_ERROR", `Request failed with status ${response.status}.`, response.status, requestId);
}

async function request(path: string, file: File, signal: AbortSignal): Promise<Response> {
  const formData = new FormData();
  formData.append("file", file);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { method: "POST", body: formData, signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiClientError("CLIENT_TIMEOUT", "The request took too long and was cancelled.", null, null);
    }
    throw new ApiClientError("NETWORK_ERROR", "Could not reach the MaskGuard server.", null, null);
  }

  const requestId = response.headers.get("X-Request-ID");
  if (!response.ok) {
    throw await readErrorBody(response, requestId);
  }
  return response;
}

function withTimeout<T>(run: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  return run(controller.signal).finally(() => clearTimeout(timer));
}

export async function getHealth(): Promise<HealthResponse> {
  return withTimeout(async (signal) => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/health`, { signal });
    } catch {
      throw new ApiClientError("NETWORK_ERROR", "Could not reach the MaskGuard server.", null, null);
    }
    if (!response.ok) {
      throw await readErrorBody(response, response.headers.get("X-Request-ID"));
    }
    return (await response.json()) as HealthResponse;
  });
}

// --- Phase 10.2: Authentication status (read-only; no tokens ever
// touch this client — the session lives entirely in an HttpOnly cookie
// the browser attaches automatically, never read or set by this code). --

export interface AuthMeResponse {
  authenticated: boolean;
  subject?: string;
  issuer?: string;
  display_name?: string | null;
  email?: string | null;
  /** Phase 10.3: the caller's own resolved permissions — a read-only
   * projection of what the backend already enforces server-side, never a
   * second source of truth. UX only (e.g. deciding whether to show a
   * "you don't have review access" notice); the backend remains
   * authoritative for every actual request. */
  permissions?: string[];
}

/** Always resolves (never throws) — a 404 means OIDC isn't configured on
 * this deployment at all, which this function reports the same way as
 * "not authenticated" so callers never need a separate "auth not
 * configured" branch. */
export async function getAuthStatus(): Promise<AuthMeResponse> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/me`);
    if (!response.ok) {
      return { authenticated: false };
    }
    return (await response.json()) as AuthMeResponse;
  } catch {
    return { authenticated: false };
  }
}

/** POSTs to the logout endpoint (CSRF-protected via Origin validation
 * server-side, Phase 10.2 §29) — never reads/writes any token itself. */
export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/api/v1/auth/logout`, { method: "POST" });
  } catch {
    // best-effort — the server-side session may still be valid if this
    // fails, but there is nothing meaningful for the UI to do beyond
    // letting the user retry (no token/local state exists to roll back).
  }
}

export async function analyzeImage(file: File): Promise<AnalyzeResponse> {
  return withTimeout(async (signal) => {
    const response = await request("/api/v1/analyze", file, signal);
    return (await response.json()) as AnalyzeResponse;
  });
}

export async function verifyImage(file: File): Promise<VerifyResponse> {
  return withTimeout(async (signal) => {
    const response = await request("/api/v1/verify", file, signal);
    return (await response.json()) as VerifyResponse;
  });
}

export type RedactResult =
  | { kind: "image"; blob: Blob; requestId: string | null }
  | { kind: "blocked"; detail: BlockedRedactResponse; requestId: string | null };

export async function redactImage(file: File): Promise<RedactResult> {
  return withTimeout(async (signal) => {
    const response = await request("/api/v1/redact", file, signal);
    const requestId = response.headers.get("X-Request-ID");
    const contentType = response.headers.get("Content-Type") ?? "";

    if (contentType.startsWith("image/")) {
      const blob = await response.blob();
      return { kind: "image", blob, requestId };
    }

    // Strict Mode withheld output — a 200 JSON body, not an error
    // (Phase 8.1 §18/§40, §16 of this phase's brief).
    const detail = (await response.json()) as BlockedRedactResponse;
    return { kind: "blocked", detail, requestId };
  });
}

// --- Phase 8.3: Human Review ----------------------------------------------

export type ReviewResult =
  | { kind: "image"; blob: Blob; headers: ReviewImageHeaders; requestId: string | null }
  | { kind: "blocked"; detail: BlockedReviewResponse; requestId: string | null };

/** Submits accept/reject decisions and/or manual detections for the SAME
 * original file a prior `analyzeImage()` call returned `review_token` for.
 * This module never inspects `items` — it only carries whatever
 * `review_token`/`items` the caller (Home.tsx's review UI state) built, per
 * `ReviewItemRequest`'s own shape guarantee: no risk_level/action/
 * confidence field exists to smuggle through in the first place (§30/§31).
 */
export async function submitReview(
  file: File,
  reviewToken: string,
  items: ReviewItemRequest[],
): Promise<ReviewResult> {
  return withTimeout(async (signal) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("review", JSON.stringify({ review_token: reviewToken, items }));

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/api/v1/review`, { method: "POST", body: formData, signal });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new ApiClientError("CLIENT_TIMEOUT", "The request took too long and was cancelled.", null, null);
      }
      throw new ApiClientError("NETWORK_ERROR", "Could not reach the MaskGuard server.", null, null);
    }

    const requestId = response.headers.get("X-Request-ID");
    if (!response.ok) {
      throw await readErrorBody(response, requestId);
    }

    const contentType = response.headers.get("Content-Type") ?? "";
    if (contentType.startsWith("image/")) {
      const blob = await response.blob();
      const headers: ReviewImageHeaders = {
        status: response.headers.get("X-Review-Status") ?? "PASSED",
        needsHumanReview: response.headers.get("X-Review-Needs-Human-Review") === "true",
        blocked: response.headers.get("X-Review-Blocked") === "true",
        detectionCount: Number(response.headers.get("X-Review-Detection-Count") ?? "0"),
      };
      return { kind: "image", blob, headers, requestId };
    }

    const detail = (await response.json()) as BlockedReviewResponse;
    return { kind: "blocked", detail, requestId };
  });
}
