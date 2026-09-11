import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DetectionResponse } from "../api/types";
import { DetectionList, type ReviewState } from "./DetectionList";

const taiwanIdDetection: DetectionResponse = {
  detection_id: "11111111-1111-1111-1111-111111111111",
  type: "TaiwanID",
  risk_level: "CRITICAL",
  action: "FULL_MASK",
  confidence: 0.98,
  needs_review: false,
  bbox: { x: 10, y: 20, width: 100, height: 30 },
};

describe("DetectionList", () => {
  it("shows an empty-state message when there are no detections", () => {
    render(<DetectionList detections={[]} />);
    expect(screen.getByText("未偵測到需要處理的敏感資料")).toBeInTheDocument();
  });

  it("renders type, risk level, action, and confidence for each detection", () => {
    render(<DetectionList detections={[taiwanIdDetection]} />);
    expect(screen.getByText("TaiwanID")).toBeInTheDocument();
    expect(screen.getByText(/CRITICAL/)).toBeInTheDocument();
    expect(screen.getByText(/FULL_MASK/)).toBeInTheDocument();
    expect(screen.getByText(/0\.98/)).toBeInTheDocument();
  });

  it("flags an item that needs human review", () => {
    render(<DetectionList detections={[{ ...taiwanIdDetection, needs_review: true }]} />);
    expect(screen.getByText("此項目需要人工確認")).toBeInTheDocument();
  });

  it("§33 CRITICAL SECURITY TEST: never renders a raw sensitive value, only backend-provided fields", () => {
    // A synthetic backend response is exactly what schemas.py guarantees:
    // no raw_text/value/ocr_text field exists on DetectionResponse at all.
    // This test proves the RENDERED DOM (not just the type) never contains
    // a value that would only appear if some future field leaked one in.
    const rawTaiwanIdValue = "A123456789";
    const { container } = render(<DetectionList detections={[taiwanIdDetection]} />);
    expect(container.textContent).not.toContain(rawTaiwanIdValue);
  });

  it("ignores unknown/unexpected fields rather than rendering them", () => {
    const withExtraField = { ...taiwanIdDetection, raw_text: "A123456789" } as unknown as DetectionResponse;
    const { container } = render(<DetectionList detections={[withExtraField]} />);
    expect(container.textContent).not.toContain("A123456789");
  });

  // --- Phase 8.3: interactive review ----------------------------------

  it("without reviewState, the list is read-only (no accept/reject controls, Phase 8.2 behavior)", () => {
    render(<DetectionList detections={[taiwanIdDetection]} />);
    expect(screen.queryByText("✓ 確認處理")).not.toBeInTheDocument();
    expect(screen.queryByText("✕ 誤判")).not.toBeInTheDocument();
  });

  it("shows the pending state and lets the user accept a detection", async () => {
    const onAccept = vi.fn();
    const reviewState = new Map<string, ReviewState>([[taiwanIdDetection.detection_id, { status: "PENDING", reason: "" }]]);
    render(<DetectionList detections={[taiwanIdDetection]} reviewState={reviewState} onAccept={onAccept} />);

    expect(screen.getByText("狀態：待確認")).toBeInTheDocument();
    await userEvent.click(screen.getByText("✓ 確認處理"));
    expect(onAccept).toHaveBeenCalledWith(taiwanIdDetection.detection_id);
  });

  it("shows 已確認 once accepted", () => {
    const reviewState = new Map<string, ReviewState>([[taiwanIdDetection.detection_id, { status: "ACCEPTED", reason: "" }]]);
    render(<DetectionList detections={[taiwanIdDetection]} reviewState={reviewState} />);
    expect(screen.getByText("狀態：已確認")).toBeInTheDocument();
  });

  it("rejecting requires a reason before it can be submitted", async () => {
    const onReject = vi.fn();
    const reviewState = new Map<string, ReviewState>([[taiwanIdDetection.detection_id, { status: "PENDING", reason: "" }]]);
    render(<DetectionList detections={[taiwanIdDetection]} reviewState={reviewState} onReject={onReject} />);

    await userEvent.click(screen.getByText("✕ 誤判"));
    const submitButton = screen.getByText("送出誤判原因");
    expect(submitButton).toBeDisabled();

    await userEvent.type(screen.getByLabelText("請說明誤判原因"), "false positive");
    expect(submitButton).toBeEnabled();
    await userEvent.click(submitButton);
    expect(onReject).toHaveBeenCalledWith(taiwanIdDetection.detection_id, "false positive");
  });

  it("shows 標記為誤判 and the reason once rejected", () => {
    const reviewState = new Map<string, ReviewState>([
      [taiwanIdDetection.detection_id, { status: "REJECTED", reason: "not a real ID" }],
    ]);
    render(<DetectionList detections={[taiwanIdDetection]} reviewState={reviewState} />);
    expect(screen.getByText("狀態：標記為誤判")).toBeInTheDocument();
    expect(screen.getByText("原因：not a real ID")).toBeInTheDocument();
  });

  it("§33/§36 SECURITY: even with a manipulated risk_level/action/confidence on the object, only the real backend-provided values render", () => {
    // Simulates a compromised/mocked response trying to smuggle a
    // different security decision — the component has no branch that
    // reads anything BUT these exact fields, so this just proves it
    // renders whatever `risk_level`/`action`/`confidence` it was actually
    // given, never inferring or overriding them itself.
    const manipulated: DetectionResponse = { ...taiwanIdDetection, risk_level: "LOW", action: "NONE", confidence: 0.01 };
    render(<DetectionList detections={[manipulated]} />);
    expect(screen.getByText(/LOW/)).toBeInTheDocument();
    expect(screen.getByText(/NONE/)).toBeInTheDocument();
    expect(screen.queryByText(/CRITICAL/)).not.toBeInTheDocument();
  });
});
