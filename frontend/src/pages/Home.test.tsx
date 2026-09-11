import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClientError } from "../api/client";
import type { AnalyzeResponse } from "../api/types";
import { Home } from "./Home";
import { renderWithLanguage as render } from "../test/renderWithLanguage";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    analyzeImage: vi.fn(),
    redactImage: vi.fn(),
    submitReview: vi.fn(),
  };
});

import { analyzeImage, redactImage } from "../api/client";

const taiwanIdAnalyze: AnalyzeResponse = {
  status: "PASSED",
  needs_human_review: false,
  blocked: false,
  detections: [
    { detection_id: "det-taiwan-id-1", type: "TaiwanID", risk_level: "CRITICAL", action: "FULL_MASK", confidence: 0.98, needs_review: false, bbox: { x: 10, y: 10, width: 50, height: 20 } },
  ],
  verification: { status: "PASSED", attempts: 1, residual_count: 0, needs_human_review: false },
  summary: { total_detections: 1, critical_count: 1, needs_review_count: 0, blocked: false },
  review_token: "fake-review-token",
};

function makeImageFile(): File {
  return new File(["fake-png-bytes"], "photo.png", { type: "image/png" });
}

describe("Home page", () => {
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;

  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:mock-url");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    // Unmount (which may call URL.revokeObjectURL from the effect cleanup)
    // BEFORE restoring the original (jsdom doesn't implement these at all,
    // so "original" is `undefined`) — otherwise a real component unmount
    // during React Testing Library's own auto-cleanup would call an
    // undefined function.
    cleanup();
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    vi.clearAllMocks();
  });

  it("shows the empty-state prompt before any image is selected", () => {
    render(<Home />);
    expect(screen.getByText("請上傳圖片開始分析")).toBeInTheDocument();
  });

  it("shows an image preview after a file is selected (upload -> preview)", async () => {
    render(<Home />);
    const input = screen.getByLabelText(/選擇圖片/);
    await userEvent.upload(input, makeImageFile());

    expect(screen.getByAltText("原始圖片預覽")).toBeInTheDocument();
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(File));
  });

  it("full flow: select -> analyze -> shows detections, status, and risk/action/confidence", async () => {
    (analyzeImage as ReturnType<typeof vi.fn>).mockResolvedValue(taiwanIdAnalyze);
    render(<Home />);

    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
    await userEvent.click(screen.getByRole("button", { name: "開始分析" }));

    await waitFor(() => expect(screen.getByText("TaiwanID")).toBeInTheDocument());
    expect(screen.getByText(/分析完成/)).toBeInTheDocument();
    expect(screen.getByText(/CRITICAL/)).toBeInTheDocument();
    expect(screen.getByText(/FULL_MASK/)).toBeInTheDocument();
    expect(screen.getByText(/0\.98/)).toBeInTheDocument();
  });

  it("shows a processing indicator while analyzing and disables the button against double submission", async () => {
    let resolveAnalyze: (value: AnalyzeResponse) => void = () => {};
    (analyzeImage as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise<AnalyzeResponse>((resolve) => {
        resolveAnalyze = resolve;
      }),
    );
    render(<Home />);
    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());

    const analyzeButton = screen.getByRole("button", { name: "開始分析" });
    await userEvent.click(analyzeButton);

    expect(screen.getByText("分析中…")).toBeInTheDocument();
    expect(analyzeButton).toBeDisabled();

    resolveAnalyze(taiwanIdAnalyze);
    await waitFor(() => expect(screen.queryByText("分析中…")).not.toBeInTheDocument());
    expect(analyzeImage).toHaveBeenCalledTimes(1);
  });

  it("redact flow: shows the redacted image after clicking 執行遮罩", async () => {
    (analyzeImage as ReturnType<typeof vi.fn>).mockResolvedValue(taiwanIdAnalyze);
    const blob = new Blob(["fake-png"], { type: "image/png" });
    (redactImage as ReturnType<typeof vi.fn>).mockResolvedValue({ kind: "image", blob, requestId: "req-1" });

    render(<Home />);
    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
    await userEvent.click(screen.getByRole("button", { name: "開始分析" }));
    await waitFor(() => expect(screen.getByText("TaiwanID")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "執行遮罩" }));
    await waitFor(() => expect(screen.getByAltText("遮罩後圖片")).toBeInTheDocument());

    // Original preview must remain — redaction never replaces it (§15).
    expect(screen.getByAltText("原始圖片預覽")).toBeInTheDocument();
  });

  it("BLOCKED response: shows the blocked notice, never a fake image", async () => {
    (analyzeImage as ReturnType<typeof vi.fn>).mockResolvedValue(taiwanIdAnalyze);
    (redactImage as ReturnType<typeof vi.fn>).mockResolvedValue({
      kind: "blocked",
      detail: {
        status: "BLOCKED",
        message: "Strict Mode verification failed; output was withheld.",
        verification: { status: "FAILED", needs_human_review: true },
      },
      requestId: "req-2",
    });

    render(<Home />);
    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
    await userEvent.click(screen.getByRole("button", { name: "開始分析" }));
    await waitFor(() => expect(screen.getByText("TaiwanID")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "執行遮罩" }));
    await waitFor(() => expect(screen.getByText("輸出已被 MaskGuard 阻擋")).toBeInTheDocument());

    expect(screen.queryByAltText("遮罩後圖片")).not.toBeInTheDocument();
  });

  it("shows a friendly error message (no traceback) when analyze fails, including the request id", async () => {
    (analyzeImage as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiClientError("INVALID_IMAGE", "Uploaded file is not a supported image.", 415, "req-err-1"),
    );
    render(<Home />);
    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
    await userEvent.click(screen.getByRole("button", { name: "開始分析" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText(/上傳的檔案不是有效的圖片格式/)).toBeInTheDocument();
    expect(screen.getByText(/req-err-1/)).toBeInTheDocument();
    expect(screen.queryByText(/Traceback/)).not.toBeInTheDocument();
  });

  it("§33 CRITICAL SECURITY TEST: a CRITICAL/FULL_MASK detection never renders its raw value anywhere in the DOM", async () => {
    (analyzeImage as ReturnType<typeof vi.fn>).mockResolvedValue(taiwanIdAnalyze);
    render(<Home />);
    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
    await userEvent.click(screen.getByRole("button", { name: "開始分析" }));
    await waitFor(() => expect(screen.getByText("TaiwanID")).toBeInTheDocument());

    expect(document.body.textContent).not.toContain("A123456789");
    expect(document.body.innerHTML).not.toContain("A123456789");
  });

  it("revokes the previous preview object URL when a new image is selected", async () => {
    render(<Home />);
    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
    await userEvent.upload(screen.getByLabelText(/選擇圖片/), makeImageFile());
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  });
});
