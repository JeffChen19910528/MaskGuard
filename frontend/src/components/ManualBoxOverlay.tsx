import { scaleBBox, type DisplayScale } from "../utils/bbox";
import type { BBox } from "../api/types";
import { useLanguage } from "../i18n/LanguageContext";
import { manualDetectionTypeLabel } from "../utils/reviewTypes";

export interface PendingManualBox {
  localId: string;
  type: string;
  bbox: BBox; // ORIGINAL image coordinates — authoritative once submitted
}

interface ManualBoxOverlayProps {
  boxes: PendingManualBox[];
  scale: DisplayScale;
  displayWidth: number;
  displayHeight: number;
  onRemove?: (localId: string) => void;
}

/**
 * Renders pending MANUAL detections (Phase 8.3 §22/§23) — visually
 * distinct (green, dashed) from `DetectionOverlay`'s automatic-detection
 * boxes, each labeled as manually added so a reviewer never confuses the
 * two sources. Purely a visual layer; no pixel masking happens here
 * (§10/§22).
 */
export function ManualBoxOverlay({ boxes, scale, displayWidth, displayHeight, onRemove }: ManualBoxOverlayProps) {
  const { t } = useLanguage();
  if (displayWidth <= 0 || displayHeight <= 0) return null;

  return (
    <div className="manual-box-overlay" style={{ width: displayWidth, height: displayHeight }}>
      {boxes.map((box) => {
        const displayBox = scaleBBox(box.bbox, scale);
        const label = manualDetectionTypeLabel(box.type, t);
        return (
          <div
            key={box.localId}
            className="manual-box-overlay__box"
            style={{ left: displayBox.x, top: displayBox.y, width: displayBox.width, height: displayBox.height }}
          >
            <span className="manual-box-overlay__label">
              {t.manualBox.addedByPrefix}{label}
            </span>
            {onRemove && (
              <button
                type="button"
                className="manual-box-overlay__remove"
                onClick={() => onRemove(box.localId)}
                aria-label={t.manualBox.removeAriaLabel(label)}
              >
                ×
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
