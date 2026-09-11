import { describe, expect, it } from "vitest";
import { computeDisplayScale, scaleBBox, unscaleBBox } from "./bbox";

describe("computeDisplayScale", () => {
  it("computes a 1:1 scale when displayed at natural size", () => {
    expect(computeDisplayScale(800, 600, 800, 600)).toEqual({ scaleX: 1, scaleY: 1 });
  });

  it("computes a shrink scale when displayed smaller than natural size", () => {
    expect(computeDisplayScale(800, 600, 400, 300)).toEqual({ scaleX: 0.5, scaleY: 0.5 });
  });

  it("falls back to 1:1 when natural size is not yet known (0)", () => {
    expect(computeDisplayScale(0, 0, 400, 300)).toEqual({ scaleX: 1, scaleY: 1 });
  });
});

describe("scaleBBox", () => {
  it("scales a backend bbox purely visually, never altering the source values", () => {
    const backendBox = { x: 100, y: 50, width: 200, height: 80 };
    const scale = { scaleX: 0.5, scaleY: 0.5 };
    expect(scaleBBox(backendBox, scale)).toEqual({ x: 50, y: 25, width: 100, height: 40 });
    // Original object must be untouched — the backend value is authoritative.
    expect(backendBox).toEqual({ x: 100, y: 50, width: 200, height: 80 });
  });

  it("is a no-op at 1:1 scale", () => {
    const backendBox = { x: 10, y: 20, width: 30, height: 40 };
    expect(scaleBBox(backendBox, { scaleX: 1, scaleY: 1 })).toEqual(backendBox);
  });
});

describe("unscaleBBox (Phase 8.3 §13)", () => {
  it("is the exact inverse of scaleBBox", () => {
    const originalBox = { x: 100, y: 50, width: 200, height: 80 };
    const scale = { scaleX: 0.5, scaleY: 0.25 };
    const displayed = scaleBBox(originalBox, scale);
    expect(unscaleBBox(displayed, scale)).toEqual(originalBox);
  });

  it("converts a user-drawn on-screen box back to original image coordinates", () => {
    // Displayed at half size -> a 50x20 on-screen drag maps to 100x40 in
    // the original image's own pixel space, which is what the backend
    // must receive (§13: "Frontend converts displayed canvas coordinates
    // -> original image coordinates").
    const scale = { scaleX: 0.5, scaleY: 0.5 };
    const drawnOnScreen = { x: 20, y: 10, width: 50, height: 20 };
    expect(unscaleBBox(drawnOnScreen, scale)).toEqual({ x: 40, y: 20, width: 100, height: 40 });
  });

  it("never divides by zero when scale is not yet known", () => {
    expect(unscaleBBox({ x: 10, y: 10, width: 5, height: 5 }, { scaleX: 0, scaleY: 0 })).toEqual({
      x: 10, y: 10, width: 5, height: 5,
    });
  });
});
