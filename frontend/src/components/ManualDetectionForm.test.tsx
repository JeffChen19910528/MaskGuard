import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ManualDetectionForm } from "./ManualDetectionForm";
import { MANUAL_DETECTION_TYPES } from "../utils/reviewTypes";

describe("ManualDetectionForm", () => {
  it("only offers the server-authoritative type list (§11)", () => {
    render(
      <ManualDetectionForm
        drawEnabled={false}
        onToggleDraw={vi.fn()}
        selectedType={MANUAL_DETECTION_TYPES[0].value}
        onSelectedTypeChange={vi.fn()}
        pendingBoxes={[]}
        onRemove={vi.fn()}
      />,
    );
    const select = screen.getByLabelText("敏感資料類型") as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toEqual(MANUAL_DETECTION_TYPES.map((t) => t.value));
  });

  it("toggles draw mode on click", async () => {
    const onToggleDraw = vi.fn();
    render(
      <ManualDetectionForm
        drawEnabled={false}
        onToggleDraw={onToggleDraw}
        selectedType="Email"
        onSelectedTypeChange={vi.fn()}
        pendingBoxes={[]}
        onRemove={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByText("新增敏感區域"));
    expect(onToggleDraw).toHaveBeenCalledTimes(1);
  });

  it("shows a drawing hint only while draw mode is active", () => {
    const { rerender } = render(
      <ManualDetectionForm
        drawEnabled={false}
        onToggleDraw={vi.fn()}
        selectedType="Email"
        onSelectedTypeChange={vi.fn()}
        pendingBoxes={[]}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.queryByText(/請在原始圖片上拖曳滑鼠繪製矩形區域/)).not.toBeInTheDocument();

    rerender(
      <ManualDetectionForm
        drawEnabled
        onToggleDraw={vi.fn()}
        selectedType="Email"
        onSelectedTypeChange={vi.fn()}
        pendingBoxes={[]}
        onRemove={vi.fn()}
      />,
    );
    expect(screen.getByText(/請在原始圖片上拖曳滑鼠繪製矩形區域/)).toBeInTheDocument();
  });

  it("lists pending manual boxes with a cancel/remove action", async () => {
    const onRemove = vi.fn();
    render(
      <ManualDetectionForm
        drawEnabled={false}
        onToggleDraw={vi.fn()}
        selectedType="Email"
        onSelectedTypeChange={vi.fn()}
        pendingBoxes={[{ localId: "box-1", type: "Email", bbox: { x: 0, y: 0, width: 10, height: 10 } }]}
        onRemove={onRemove}
      />,
    );
    expect(screen.getByText(/來源：人工新增 — 電子郵件/)).toBeInTheDocument();
    await userEvent.click(screen.getByText("取消"));
    expect(onRemove).toHaveBeenCalledWith("box-1");
  });
});
