/**
 * Pure visual coordinate transform (Phase 8.2 §9): backend `bbox` values
 * are in the ORIGINAL image's pixel space and are authoritative — this
 * only scales them for whatever size the <img> is actually rendered at on
 * screen. It never recalculates, adjusts, or second-guesses a bbox value.
 */
import type { BBox } from "../api/types";

export interface DisplayScale {
  scaleX: number;
  scaleY: number;
}

export function computeDisplayScale(naturalWidth: number, naturalHeight: number, displayWidth: number, displayHeight: number): DisplayScale {
  if (naturalWidth <= 0 || naturalHeight <= 0) {
    return { scaleX: 1, scaleY: 1 };
  }
  return { scaleX: displayWidth / naturalWidth, scaleY: displayHeight / naturalHeight };
}

export function scaleBBox(bbox: BBox, scale: DisplayScale): BBox {
  return {
    x: bbox.x * scale.scaleX,
    y: bbox.y * scale.scaleY,
    width: bbox.width * scale.scaleX,
    height: bbox.height * scale.scaleY,
  };
}

/**
 * Inverse of `scaleBBox` (Phase 8.3 §13): converts a box the user drew in
 * DISPLAYED (on-screen) pixel coordinates back into the ORIGINAL image's
 * pixel coordinate space — the only coordinate system the backend accepts
 * for a manual detection. Purely visual math; the backend independently
 * re-validates the result against the real image dimensions regardless
 * (§12) — this function does not make the submitted box "trusted", it only
 * makes it CORRECT relative to what the user actually saw on screen.
 */
export function unscaleBBox(displayBox: BBox, scale: DisplayScale): BBox {
  const safeScaleX = scale.scaleX || 1;
  const safeScaleY = scale.scaleY || 1;
  return {
    x: Math.round(displayBox.x / safeScaleX),
    y: Math.round(displayBox.y / safeScaleY),
    width: Math.round(displayBox.width / safeScaleX),
    height: Math.round(displayBox.height / safeScaleY),
  };
}
