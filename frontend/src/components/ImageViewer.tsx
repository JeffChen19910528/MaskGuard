import { useLayoutEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import type { BBox, DetectionResponse } from "../api/types";
import { computeDisplayScale, unscaleBBox } from "../utils/bbox";
import { DetectionOverlay } from "./DetectionOverlay";
import { ManualBoxOverlay, type PendingManualBox } from "./ManualBoxOverlay";

interface ImageViewerProps {
  src: string;
  alt: string;
  detections?: DetectionResponse[];
  label: string;
  /** Phase 8.3 §22: pending manually-drawn boxes (ORIGINAL image
   * coordinates) to render alongside `detections`, distinguishable by
   * style (§23: "來源：自動偵測 / 人工新增"). */
  manualBoxes?: PendingManualBox[];
  onRemoveManualBox?: (localId: string) => void;
  /** When true, a mouse drag on the image draws a new manual box; the
   * resulting bbox is reported in ORIGINAL image coordinates (§13) via
   * `onBoxDrawn` — this component performs NO redaction, NO type
   * selection, and NO validation; it only reports geometry. */
  drawEnabled?: boolean;
  onBoxDrawn?: (bbox: BBox) => void;
}

/**
 * Displays one image (original preview OR redacted result) and, if given
 * `detections`, overlays their bounding boxes on top via a separate layer —
 * never by mutating the image itself (§8). Tracks the image's natural vs.
 * rendered size so `DetectionOverlay` can scale backend coordinates purely
 * visually (§9); no OCR, no recomputation of any box.
 */
export function ImageViewer({
  src, alt, detections, label, manualBoxes, onRemoveManualBox, drawEnabled, onBoxDrawn,
}: ImageViewerProps) {
  const imgRef = useRef<HTMLImageElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });
  const [displaySize, setDisplaySize] = useState({ width: 0, height: 0 });
  const [draftBox, setDraftBox] = useState<BBox | null>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);

  function measure() {
    const img = imgRef.current;
    if (!img) return;
    setNaturalSize({ width: img.naturalWidth, height: img.naturalHeight });
    setDisplaySize({ width: img.clientWidth, height: img.clientHeight });
  }

  useLayoutEffect(() => {
    if (typeof ResizeObserver === "undefined" || !imgRef.current) return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(imgRef.current);
    return () => observer.disconnect();
  }, [src]);

  const scale = computeDisplayScale(naturalSize.width, naturalSize.height, displaySize.width, displaySize.height);

  function pointerPosition(event: ReactMouseEvent): { x: number; y: number } {
    const rect = frameRef.current?.getBoundingClientRect();
    const x = rect ? event.clientX - rect.left : 0;
    const y = rect ? event.clientY - rect.top : 0;
    return { x: Math.max(0, Math.min(x, displaySize.width)), y: Math.max(0, Math.min(y, displaySize.height)) };
  }

  function handleMouseDown(event: ReactMouseEvent) {
    if (!drawEnabled) return;
    const point = pointerPosition(event);
    dragStart.current = point;
    setDraftBox({ x: point.x, y: point.y, width: 0, height: 0 });
  }

  function handleMouseMove(event: ReactMouseEvent) {
    if (!drawEnabled || !dragStart.current) return;
    const point = pointerPosition(event);
    const start = dragStart.current;
    setDraftBox({
      x: Math.min(start.x, point.x),
      y: Math.min(start.y, point.y),
      width: Math.abs(point.x - start.x),
      height: Math.abs(point.y - start.y),
    });
  }

  function handleMouseUp() {
    if (!drawEnabled || !dragStart.current || !draftBox) {
      dragStart.current = null;
      return;
    }
    dragStart.current = null;
    if (draftBox.width >= 3 && draftBox.height >= 3) {
      onBoxDrawn?.(unscaleBBox(draftBox, scale));
    }
    setDraftBox(null);
  }

  return (
    <figure className="image-viewer">
      <figcaption>{label}</figcaption>
      <div
        ref={frameRef}
        className={`image-viewer__frame${drawEnabled ? " image-viewer__frame--drawable" : ""}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => {
          dragStart.current = null;
          setDraftBox(null);
        }}
      >
        <img ref={imgRef} src={src} alt={alt} onLoad={measure} className="image-viewer__img" draggable={false} />
        {detections && detections.length > 0 && (
          <DetectionOverlay
            detections={detections}
            naturalWidth={naturalSize.width}
            naturalHeight={naturalSize.height}
            displayWidth={displaySize.width}
            displayHeight={displaySize.height}
          />
        )}
        {manualBoxes && manualBoxes.length > 0 && (
          <ManualBoxOverlay
            boxes={manualBoxes}
            scale={scale}
            displayWidth={displaySize.width}
            displayHeight={displaySize.height}
            onRemove={onRemoveManualBox}
          />
        )}
        {draftBox && (
          <svg className="detection-overlay" width={displaySize.width} height={displaySize.height} aria-hidden="true">
            <rect x={draftBox.x} y={draftBox.y} width={draftBox.width} height={draftBox.height} fill="rgba(46,125,50,0.15)" stroke="#2e7d32" strokeWidth={2} strokeDasharray="4 2" />
          </svg>
        )}
      </div>
    </figure>
  );
}
