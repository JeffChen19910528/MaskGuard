import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AnalyzeResponse, ReviewItemRequest } from "../api/types";
import { Home } from "./Home";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    analyzeImage: vi.fn(),
    redactImage: vi.fn(),
    submitReview: vi.fn(),
  };
});

import { analyzeImage, submitReview } from "../api/client";

const twoDetectionAnalyze: AnalyzeResponse = {
  status: "PASSED",
  needs_human_review: false,
  blocked: false,
  detections: [
    { detection_id: "det-taiwan-id", type: "TaiwanID", risk_level: "CRITICAL", action: "FULL_MASK", confidence: 0.98, needs_review: false, bbox: { x: 10, y: 10, width: 50, height: 20 } },
    { detection_id: "det-email", type: "Email", risk_level: "HIGH", action: "BLUR", confidence: 0.9, needs_review: false, bbox: { x: 80, y: 10, width: 60, height: 20 } },
  ],
  verification: { status: "PASSED", attempts: 1, residual_count: 0, needs_human_review: false },
  summary: { total_detections: 2, critical_count: 1, needs_review_count: 0, blocked: false },
  review_token: "signed-token-xyz",
};

function makeImageFile(): File {
  return new File(["fake-png-bytes"], "photo.png", { type: "image/png" });
}

async function analyzeAndWait() {
  render(<Home />);
  await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
  await userEvent.click(screen.getByRole("button", { name: "開始分析" }));
  await waitFor(() => expect(screen.getByText("TaiwanID")).toBeInTheDocument());
}

describe("Home page — Human Review (Phase 8.3)", () => {
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
    (analyzeImage as ReturnType<typeof vi.fn>).mockResolvedValue(twoDetectionAnalyze);
  });

  afterEach(() => {
    cleanup();
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    vi.clearAllMocks();
  });

  it("every detection starts PENDING after analyze", async () => {
    await analyzeAndWait();
    const statuses = screen.getAllByText("狀態：待確認");
    expect(statuses).toHaveLength(2);
  });

  it("accept flow: clicking 確認處理 moves a detection to 已確認, without contacting the backend", async () => {
    await analyzeAndWait();
    const acceptButtons = screen.getAllByText("✓ 確認處理");
    await userEvent.click(acceptButtons[0]);
    expect(screen.getAllByText("狀態：已確認")).toHaveLength(1);
    expect(submitReview).not.toHaveBeenCalled();
  });

  it("reject flow requires a reason and moves the detection to 標記為誤判", async () => {
    await analyzeAndWait();
    const rejectButtons = screen.getAllByText("✕ 誤判");
    await userEvent.click(rejectButtons[0]);
    await userEvent.type(screen.getAllByLabelText("請說明誤判原因")[0], "not real");
    await userEvent.click(screen.getByText("送出誤判原因"));
    expect(screen.getByText("狀態：標記為誤判")).toBeInTheDocument();
    expect(screen.getByText("原因：not real")).toBeInTheDocument();
  });

  it("submit review sends accepted/rejected decisions built from local state, never from anywhere else", async () => {
    (submitReview as ReturnType<typeof vi.fn>).mockResolvedValue({
      kind: "image",
      blob: new Blob(["x"], { type: "image/png" }),
      headers: { status: "PASSED", needsHumanReview: false, blocked: false, detectionCount: 2 },
      requestId: "req-1",
    });
    await analyzeAndWait();

    const taiwanIdItem = screen.getByText("TaiwanID").closest("li") as HTMLElement;
    const emailItem = screen.getByText("Email").closest("li") as HTMLElement;

    await userEvent.click(within(taiwanIdItem).getByText("✓ 確認處理"));
    await userEvent.click(within(emailItem).getByText("✕ 誤判"));
    await userEvent.type(within(emailItem).getByLabelText("請說明誤判原因"), "false positive");
    await userEvent.click(within(emailItem).getByText("送出誤判原因"));

    await userEvent.click(screen.getByRole("button", { name: "提交人工確認結果" }));

    await waitFor(() => expect(submitReview).toHaveBeenCalledTimes(1));
    const [, token, items] = (submitReview as ReturnType<typeof vi.fn>).mock.calls[0] as [File, string, ReviewItemRequest[]];
    expect(token).toBe("signed-token-xyz");
    expect(items).toContainEqual({ detection_id: "det-taiwan-id", review_status: "ACCEPTED" });
    expect(items).toContainEqual({ detection_id: "det-email", review_status: "REJECTED", reason: "false positive" });
  });

  it("manual box: drawing on the original image adds a pending manual detection with the selected type", async () => {
    await analyzeAndWait();

    await userEvent.click(screen.getByText("新增敏感區域"));

    const frame = document.querySelector(".image-viewer__frame") as HTMLElement;
    const img = screen.getByAltText("原始圖片預覽") as HTMLImageElement;
    vi.spyOn(frame, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100, x: 0, y: 0, toJSON: () => ({}),
    });
    Object.defineProperty(img, "naturalWidth", { value: 200, configurable: true });
    Object.defineProperty(img, "naturalHeight", { value: 100, configurable: true });
    Object.defineProperty(img, "clientWidth", { value: 200, configurable: true });
    Object.defineProperty(img, "clientHeight", { value: 100, configurable: true });
    fireEvent.load(img);

    fireEvent.mouseDown(frame, { clientX: 20, clientY: 10 });
    fireEvent.mouseMove(frame, { clientX: 70, clientY: 30 });
    fireEvent.mouseUp(frame, { clientX: 70, clientY: 30 });

    expect(screen.getByText(/來源：人工新增 — 身分證字號/)).toBeInTheDocument();
  });

  it("cancel manual box removes it from the pending list", async () => {
    await analyzeAndWait();
    await userEvent.click(screen.getByText("新增敏感區域"));

    const frame = document.querySelector(".image-viewer__frame") as HTMLElement;
    const img = screen.getByAltText("原始圖片預覽") as HTMLImageElement;
    vi.spyOn(frame, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100, x: 0, y: 0, toJSON: () => ({}),
    });
    Object.defineProperty(img, "naturalWidth", { value: 200, configurable: true });
    Object.defineProperty(img, "naturalHeight", { value: 100, configurable: true });
    Object.defineProperty(img, "clientWidth", { value: 200, configurable: true });
    Object.defineProperty(img, "clientHeight", { value: 100, configurable: true });
    fireEvent.load(img);
    fireEvent.mouseDown(frame, { clientX: 20, clientY: 10 });
    fireEvent.mouseMove(frame, { clientX: 70, clientY: 30 });
    fireEvent.mouseUp(frame, { clientX: 70, clientY: 30 });

    expect(screen.getByText(/來源：人工新增/)).toBeInTheDocument();
    await userEvent.click(screen.getAllByText("取消")[0]);
    expect(screen.queryByText(/來源：人工新增/)).not.toBeInTheDocument();
  });

  it("BLOCKED review response shows the blocked notice, never a fake reviewed image", async () => {
    (submitReview as ReturnType<typeof vi.fn>).mockResolvedValue({
      kind: "blocked",
      detail: {
        status: "BLOCKED",
        message: "Strict Mode verification failed; output was withheld.",
        verification: { status: "FAILED", needs_human_review: true },
      },
      requestId: "req-2",
    });
    await analyzeAndWait();
    await userEvent.click(screen.getByRole("button", { name: "提交人工確認結果" }));

    await waitFor(() => expect(screen.getByText("輸出已被 MaskGuard 阻擋")).toBeInTheDocument());
    expect(screen.queryByAltText("人工確認後之遮罩圖片")).not.toBeInTheDocument();
  });

  it("verification failure (non-blocked) does not display the image as safe", async () => {
    (submitReview as ReturnType<typeof vi.fn>).mockResolvedValue({
      kind: "image",
      blob: new Blob(["x"], { type: "image/png" }),
      headers: { status: "FAILED", needsHumanReview: true, blocked: false, detectionCount: 2 },
      requestId: "req-3",
    });
    await analyzeAndWait();
    await userEvent.click(screen.getByRole("button", { name: "提交人工確認結果" }));

    await waitFor(() => expect(screen.getByText(/驗證未通過，請勿使用此輸出。/)).toBeInTheDocument());
    expect(screen.queryByAltText("人工確認後之遮罩圖片")).not.toBeInTheDocument();
  });

  it("successful review result shows 驗證通過 and the reviewed image", async () => {
    (submitReview as ReturnType<typeof vi.fn>).mockResolvedValue({
      kind: "image",
      blob: new Blob(["x"], { type: "image/png" }),
      headers: { status: "PASSED", needsHumanReview: false, blocked: false, detectionCount: 2 },
      requestId: "req-4",
    });
    await analyzeAndWait();
    await userEvent.click(screen.getByRole("button", { name: "提交人工確認結果" }));

    await waitFor(() => expect(screen.getByText(/驗證通過/)).toBeInTheDocument());
    expect(screen.getByAltText("人工確認後之遮罩圖片")).toBeInTheDocument();
    // Original must remain visible and unreplaced (§24).
    expect(screen.getByAltText("原始圖片預覽")).toBeInTheDocument();
  });

  it("disables the submit button while a review is in flight (no duplicate submission)", async () => {
    let resolveReview: (value: unknown) => void = () => {};
    (submitReview as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((resolve) => {
        resolveReview = resolve;
      }),
    );
    await analyzeAndWait();
    const submitButton = screen.getByRole("button", { name: "提交人工確認結果" });
    await userEvent.click(submitButton);

    expect(screen.getByText("人工確認處理中…")).toBeInTheDocument();
    expect(submitButton).toBeDisabled();

    resolveReview({
      kind: "image",
      blob: new Blob(["x"], { type: "image/png" }),
      headers: { status: "PASSED", needsHumanReview: false, blocked: false, detectionCount: 2 },
      requestId: null,
    });
    await waitFor(() => expect(screen.queryByText("人工確認處理中…")).not.toBeInTheDocument());
    expect(submitReview).toHaveBeenCalledTimes(1);
  });

  it("§28 error handling: an expired-review error shows a friendly Traditional Chinese message", async () => {
    const { ApiClientError } = await import("../api/client");
    (submitReview as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiClientError("REVIEW_EXPIRED", "This review context has expired.", 409, "req-5"),
    );
    await analyzeAndWait();
    await userEvent.click(screen.getByRole("button", { name: "提交人工確認結果" }));

    await waitFor(() => expect(screen.getByText(/人工確認資料已過期，請重新分析圖片。/)).toBeInTheDocument());
  });

  it("§33/§36 SECURITY: the review submission never includes risk/action/confidence, even indirectly", async () => {
    (submitReview as ReturnType<typeof vi.fn>).mockResolvedValue({
      kind: "image",
      blob: new Blob(["x"], { type: "image/png" }),
      headers: { status: "PASSED", needsHumanReview: false, blocked: false, detectionCount: 2 },
      requestId: null,
    });
    await analyzeAndWait();
    await userEvent.click(screen.getAllByText("✓ 確認處理")[0]);
    await userEvent.click(screen.getByRole("button", { name: "提交人工確認結果" }));

    await waitFor(() => expect(submitReview).toHaveBeenCalled());
    const [, , items] = (submitReview as ReturnType<typeof vi.fn>).mock.calls[0] as [File, string, ReviewItemRequest[]];
    for (const item of items) {
      expect(item).not.toHaveProperty("risk_level");
      expect(item).not.toHaveProperty("action");
      expect(item).not.toHaveProperty("confidence");
    }
  });

  it("§33 raw sensitive value never appears anywhere in the DOM during a review session", async () => {
    await analyzeAndWait();
    await userEvent.click(screen.getAllByText("✓ 確認處理")[0]);
    expect(document.body.textContent).not.toContain("A123456789");
    expect(document.body.innerHTML).not.toContain("A123456789");
  });
});
