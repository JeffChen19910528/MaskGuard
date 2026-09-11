import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DetectionResponse, SummaryResponse } from "../api/types";
import { StatusBanner } from "./StatusBanner";
import { renderWithLanguage as render } from "../test/renderWithLanguage";

const summary: SummaryResponse = { total_detections: 2, critical_count: 1, needs_review_count: 0, blocked: false };
const detections: DetectionResponse[] = [
  { detection_id: "d1", type: "TaiwanID", risk_level: "CRITICAL", action: "FULL_MASK", confidence: 0.9, needs_review: false, bbox: { x: 0, y: 0, width: 1, height: 1 } },
  { detection_id: "d2", type: "Email", risk_level: "HIGH", action: "BLUR", confidence: 0.8, needs_review: false, bbox: { x: 0, y: 0, width: 1, height: 1 } },
];

describe("StatusBanner", () => {
  it.each([
    ["PASSED", "分析完成"],
    ["NEEDS_REVIEW", "需要人工確認"],
    ["BLOCKED", "已阻擋輸出"],
    ["FAILED", "處理失敗"],
  ])("displays the Traditional Chinese label for backend status %s", (status, expectedLabel) => {
    render(<StatusBanner status={status} summary={summary} detections={detections} />);
    expect(screen.getByText(new RegExp(expectedLabel))).toBeInTheDocument();
  });

  it("displays backend-provided counts without reinterpreting them", () => {
    render(<StatusBanner status="PASSED" summary={summary} detections={detections} />);
    expect(screen.getByTestId("count-total")).toHaveTextContent("2"); // summary.total_detections (backend)
    expect(screen.getByTestId("count-critical")).toHaveTextContent("1"); // summary.critical_count (backend)
    expect(screen.getByTestId("count-high")).toHaveTextContent("1"); // counted from detections[].risk_level
  });

  it("uses role=status and aria-live=polite so screen readers announce changes", () => {
    render(<StatusBanner status="PASSED" summary={summary} detections={detections} />);
    const banner = screen.getByRole("status");
    expect(banner).toHaveAttribute("aria-live", "polite");
  });
});
