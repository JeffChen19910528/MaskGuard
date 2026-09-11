import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, analyzeImage, getHealth, redactImage, submitReview, verifyImage } from "./client";
import type { ReviewItemRequest } from "./types";

function jsonResponse(body: unknown, init: ResponseInit & { requestId?: string } = {}) {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (init.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init.status ?? 200, headers });
}

const testFile = new File(["fake-image-bytes"], "upload.png", { type: "image/png" });

describe("api client", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("getHealth parses a successful response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ status: "ok", api_version: "1.0.0", app_version: "0.1.0", ocr_engine_available: true }),
    );
    const result = await getHealth();
    expect(result.status).toBe("ok");
  });

  it("analyzeImage sends a multipart/form-data POST with the file", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({
        status: "PASSED",
        needs_human_review: false,
        blocked: false,
        detections: [],
        verification: { status: "PASSED", attempts: 1, residual_count: 0, needs_human_review: false },
        summary: { total_detections: 0, critical_count: 0, needs_review_count: 0, blocked: false },
      }),
    );

    await analyzeImage(testFile);

    const [url, options] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toContain("/api/v1/analyze");
    expect(options.method).toBe("POST");
    expect(options.body).toBeInstanceOf(FormData);
    expect((options.body as FormData).get("file")).toBe(testFile);
  });

  it("redactImage returns an image blob when the response is image/png", async () => {
    const bytes = new Uint8Array([1, 2, 3]);
    const headers = new Headers({ "Content-Type": "image/png", "X-Request-ID": "req-1" });
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(new Response(bytes, { status: 200, headers }));

    const result = await redactImage(testFile);
    expect(result.kind).toBe("image");
    if (result.kind === "image") {
      // Not `toBeInstanceOf(Blob)`: Node's built-in fetch (undici) and
      // jsdom's `Blob` global are different realms, so a real Blob
      // constructed by undici's Response.blob() legitimately fails a
      // same-realm `instanceof Blob` check here even though it IS a Blob.
      expect(result.blob.size).toBe(3);
      expect(typeof result.blob.arrayBuffer).toBe("function");
      expect(result.requestId).toBe("req-1");
    }
  });

  it("redactImage returns a blocked result when the response is JSON status BLOCKED", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(
        {
          status: "BLOCKED",
          message: "Strict Mode verification failed; output was withheld.",
          verification: { status: "FAILED", needs_human_review: true },
        },
        { requestId: "req-2" },
      ),
    );

    const result = await redactImage(testFile);
    expect(result.kind).toBe("blocked");
    if (result.kind === "blocked") {
      expect(result.detail.status).toBe("BLOCKED");
      expect(result.detail.verification.needs_human_review).toBe(true);
      expect(result.requestId).toBe("req-2");
    }
  });

  it("verifyImage parses a clean/dirty scan result", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ clean: false, found_types: ["TaiwanID"], found_critical_types: ["TaiwanID"] }),
    );
    const result = await verifyImage(testFile);
    expect(result.clean).toBe(false);
    expect(result.found_critical_types).toContain("TaiwanID");
  });

  it("throws an ApiClientError with code/message/requestId on a backend error response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(
        { error: { code: "INVALID_IMAGE", message: "Uploaded file is not a supported image.", request_id: "req-3" } },
        { status: 415, requestId: "req-3" },
      ),
    );

    await expect(analyzeImage(testFile)).rejects.toMatchObject({
      code: "INVALID_IMAGE",
      status: 415,
      requestId: "req-3",
    });
  });

  it("normalizes a raw network failure into a NETWORK_ERROR ApiClientError", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(analyzeImage(testFile)).rejects.toBeInstanceOf(ApiClientError);
    await expect(analyzeImage(testFile)).rejects.toMatchObject({ code: "NETWORK_ERROR" });
  });

  it("never includes the traceback or raw exception text from a malformed error body", async () => {
    const headers = new Headers({ "Content-Type": "text/plain" });
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("Traceback (most recent call last): ...", { status: 500, headers }),
    );
    try {
      await analyzeImage(testFile);
      expect.unreachable();
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).message).not.toContain("Traceback");
    }
  });

  // --- Phase 8.3: submitReview ---------------------------------------

  it("submitReview sends the file AND the review JSON as multipart fields", async () => {
    const headers = new Headers({ "Content-Type": "image/png", "X-Request-ID": "req-9", "X-Review-Status": "PASSED", "X-Review-Needs-Human-Review": "false", "X-Review-Blocked": "false", "X-Review-Detection-Count": "1" });
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(new Response(new Uint8Array([9, 9]), { status: 200, headers }));

    const items: ReviewItemRequest[] = [{ detection_id: "d1", review_status: "ACCEPTED" }];
    const result = await submitReview(testFile, "signed-token-abc", items);

    const [url, options] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(String(url)).toContain("/api/v1/review");
    const body = options.body as FormData;
    expect(body.get("file")).toBe(testFile);
    expect(JSON.parse(body.get("review") as string)).toEqual({ review_token: "signed-token-abc", items });

    expect(result.kind).toBe("image");
    if (result.kind === "image") {
      expect(result.headers.status).toBe("PASSED");
      expect(result.headers.detectionCount).toBe(1);
    }
  });

  it("submitReview never sends risk_level/action/confidence overrides even if the caller tries to smuggle them", async () => {
    const headers = new Headers({ "Content-Type": "image/png", "X-Review-Status": "PASSED", "X-Review-Needs-Human-Review": "false", "X-Review-Blocked": "false", "X-Review-Detection-Count": "0" });
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(new Response(new Uint8Array([1]), { status: 200, headers }));

    // ReviewItemRequest's ACCEPTED variant structurally has no such fields
    // — this is a compile-time guarantee, not just a runtime one.
    const items: ReviewItemRequest[] = [{ detection_id: "d1", review_status: "ACCEPTED" }];
    await submitReview(testFile, "tok", items);

    const [, options] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    const sentReview = JSON.parse((options.body as FormData).get("review") as string);
    expect(sentReview.items[0]).not.toHaveProperty("risk_level");
    expect(sentReview.items[0]).not.toHaveProperty("action");
    expect(sentReview.items[0]).not.toHaveProperty("confidence");
  });

  it("submitReview returns a blocked result for a JSON (non-image) response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({
        status: "BLOCKED",
        message: "Strict Mode verification failed; output was withheld.",
        verification: { status: "FAILED", needs_human_review: true },
      }),
    );
    const result = await submitReview(testFile, "tok", []);
    expect(result.kind).toBe("blocked");
    if (result.kind === "blocked") {
      expect(result.detail.status).toBe("BLOCKED");
    }
  });

  it("submitReview surfaces REVIEW_EXPIRED/REVIEW_CONFLICT as typed ApiClientErrors", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(
        { error: { code: "REVIEW_EXPIRED", message: "This review context has expired.", request_id: "r1" } },
        { status: 409 },
      ),
    );
    await expect(submitReview(testFile, "tok", [])).rejects.toMatchObject({ code: "REVIEW_EXPIRED", status: 409 });
  });
});
