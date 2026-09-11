import type { DetectionResponse } from "../api/types";
import { useLanguage } from "../i18n/LanguageContext";
import { computeDisplayScale, scaleBBox } from "../utils/bbox";
import { riskColor, riskLabel } from "../utils/presentation";

interface DetectionOverlayProps {
  detections: DetectionResponse[];
  naturalWidth: number;
  naturalHeight: number;
  displayWidth: number;
  displayHeight: number;
}

/**
 * Draws backend-supplied bounding boxes over the displayed image. The
 * boxes are drawn on a separate absolutely-positioned layer — original
 * image pixels are never touched (Phase 8.2 §8). Coordinates are ONLY
 * visually rescaled to match however large the <img> happens to be
 * rendered on screen; the underlying (x, y, width, height) values always
 * come straight from the backend response (§9) — nothing here recomputes
 * or infers a box.
 */
export function DetectionOverlay({ detections, naturalWidth, naturalHeight, displayWidth, displayHeight }: DetectionOverlayProps) {
  const { t } = useLanguage();
  if (naturalWidth <= 0 || naturalHeight <= 0 || displayWidth <= 0 || displayHeight <= 0) {
    return null;
  }
  const scale = computeDisplayScale(naturalWidth, naturalHeight, displayWidth, displayHeight);

  return (
    <svg
      className="detection-overlay"
      width={displayWidth}
      height={displayHeight}
      viewBox={`0 0 ${displayWidth} ${displayHeight}`}
      role="img"
      aria-label={t.detectionOverlay.ariaLabel(detections.length)}
    >
      {detections.map((detection, index) => {
        const box = scaleBBox(detection.bbox, scale);
        const color = riskColor(detection.risk_level);
        return (
          <g key={index}>
            <rect
              x={box.x}
              y={box.y}
              width={box.width}
              height={box.height}
              fill="none"
              stroke={color}
              strokeWidth={2}
            >
              <title>
                {detection.type} — {riskLabel(detection.risk_level, t)}
              </title>
            </rect>
          </g>
        );
      })}
    </svg>
  );
}
