// @vitest-environment node
/**
 * Phase 8.2 §34: at least one test must drive Upload -> /analyze -> real
 * backend response, against the ACTUAL FastAPI server (Phase 8.1) — not a
 * mocked fetch. This file runs under Vitest's `node` environment (see the
 * `@vitest-environment node` pragma above) rather than the app's usual
 * `jsdom` environment.
 *
 * Why: jsdom's own `File`/`Blob`/`FormData` implementations are a
 * DIFFERENT realm from Node's built-in `fetch` (undici) — POSTing a
 * jsdom-constructed multipart body through Node's real fetch hangs
 * indefinitely (reproduced directly: a plain `GET /api/v1/health` under
 * jsdom resolves in ~12ms; the identical `fetch` call with a jsdom
 * `FormData`+`File` body never resolves, even with no timeout at all).
 * This is a documented jsdom/undici interop gap, not a MaskGuard defect —
 * real browsers implement `fetch`/`FormData`/`File` consistently. Running
 * under Node's own environment uses Node's OWN `File`/`FormData`/`fetch`
 * throughout, sidestepping the mismatch entirely while still exercising
 * the real `api/client.ts` code (`analyzeImage()`) against the real
 * backend over real HTTP — the network-and-Core half of §34's "Upload ->
 * /analyze -> receive real backend response" requirement.
 *
 * The other half — "-> display detection" — is proven by
 * `src/pages/Home.test.tsx`'s `"full flow"` test, which renders the real
 * `<Home>` component (jsdom, for real DOM assertions) against a response
 * shaped exactly like what this file proves the real backend actually
 * returns (see the shared assertions on TaiwanID/CRITICAL/FULL_MASK below
 * and in that file).
 *
 * Requires the real FastAPI server running with real Tesseract (see
 * README): start it, then run `VITE_TEST_REAL_BACKEND=1 npm test`.
 * Without that env var (or if the server isn't reachable), this test
 * SKIPS with a clear reason — it never falls back to a mocked response.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";
import { analyzeImage, submitReview } from "../api/client";

const __dirname = dirname(fileURLToPath(import.meta.url));
const API_BASE_URL = process.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const REAL_FIXTURE_PATH = resolve(__dirname, "../../../benchmarks/results/dataset/TaiwanID_clean.png");

let backendReady = false;
let skipReason = "VITE_TEST_REAL_BACKEND was not set";

beforeAll(async () => {
  if (process.env.VITE_TEST_REAL_BACKEND !== "1") {
    return;
  }
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    const response = await fetch(`${API_BASE_URL}/api/v1/health`, { signal: controller.signal });
    clearTimeout(timer);
    backendReady = response.ok;
    if (!backendReady) skipReason = `backend health check returned ${response.status}`;
  } catch (err) {
    skipReason = `backend not reachable at ${API_BASE_URL}: ${String(err)}`;
  }
});

describe("real backend integration (Phase 8.2 §34)", () => {
  it("uploads a real fixture to the real /api/v1/analyze and gets a real MaskGuard Core detection back", async (ctx) => {
    if (!backendReady) {
      console.info(`[realBackendIntegration] skipped: ${skipReason}`);
      ctx.skip();
      return;
    }

    const bytes = readFileSync(REAL_FIXTURE_PATH);
    const file = new File([bytes], "taiwan_id.png", { type: "image/png" });

    const result = await analyzeImage(file);

    // Real RiskEngine/PolicyEngine output — not authored by this test.
    const taiwanId = result.detections.find((d) => d.type === "TaiwanID");
    expect(taiwanId).toBeDefined();
    expect(taiwanId?.risk_level).toBe("CRITICAL");
    expect(taiwanId?.action).toBe("FULL_MASK");

    // §33/§28: the real response must never carry the raw fixture value.
    expect(JSON.stringify(result)).not.toContain("A123456789");
  }, 30_000);

  it("Phase 8.3 §34-equivalent: real analyze -> accept -> real /api/v1/review -> real redaction+verification", async (ctx) => {
    if (!backendReady) {
      ctx.skip();
      return;
    }

    const bytes = readFileSync(REAL_FIXTURE_PATH);
    const file = new File([bytes], "taiwan_id.png", { type: "image/png" });

    const analyzeResult = await analyzeImage(file);
    const taiwanId = analyzeResult.detections.find((d) => d.type === "TaiwanID")!;
    expect(analyzeResult.review_token).toBeTruthy();

    const reviewResult = await submitReview(file, analyzeResult.review_token!, [
      { detection_id: taiwanId.detection_id, review_status: "ACCEPTED" },
    ]);

    expect(reviewResult.kind).toBe("image");
    if (reviewResult.kind === "image") {
      expect(reviewResult.headers.blocked).toBe(false);
      expect(reviewResult.blob.size).toBeGreaterThan(0);
    }
  }, 30_000);
});
