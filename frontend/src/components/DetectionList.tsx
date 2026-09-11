import { useState } from "react";
import type { DetectionResponse, ReviewStatus } from "../api/types";
import { riskColor, riskLabel } from "../utils/presentation";

export interface ReviewState {
  status: ReviewStatus;
  reason: string;
}

interface DetectionListProps {
  detections: DetectionResponse[];
  /** Phase 8.3 §21/§22: local-only per-detection review state, keyed by
   * `detection_id`. `undefined` -> read-only display (Phase 8.2 behavior,
   * used before a review session starts). Passing this prop turns the list
   * interactive (accept/reject buttons appear). Nothing here is sent to
   * the backend until Home.tsx's "提交人工確認結果" action collects it. */
  reviewState?: Map<string, ReviewState>;
  onAccept?: (detectionId: string) => void;
  onReject?: (detectionId: string, reason: string) => void;
}

const STATUS_LABELS: Record<ReviewStatus, string> = {
  PENDING: "待確認",
  ACCEPTED: "已確認",
  REJECTED: "標記為誤判",
};

/**
 * Side/lower panel listing every detection. Renders ONLY the fields the
 * backend schema defines (type/risk_level/action/confidence/needs_review) —
 * never a raw matched value. Even if a future backend response somehow
 * included an unexpected field (e.g. a stray `value`/`raw_text`/`ocr_text`
 * key), this component only ever reads the named fields below, so an
 * unknown field is silently ignored rather than rendered (Phase 8.2 §11).
 *
 * Accept/Reject (Phase 8.3 §7/§8/§21) only ever update LOCAL review intent
 * via `onAccept`/`onReject` — this component never decides a security
 * outcome, computes a risk level, or calls the backend itself.
 */
export function DetectionList({ detections, reviewState, onAccept, onReject }: DetectionListProps) {
  if (detections.length === 0) {
    return <p className="detection-list__empty">未偵測到需要處理的敏感資料</p>;
  }

  return (
    <ul className="detection-list" aria-label="偵測結果">
      {detections.map((detection) => (
        <DetectionListItem
          key={detection.detection_id}
          detection={detection}
          review={reviewState?.get(detection.detection_id)}
          onAccept={onAccept}
          onReject={onReject}
        />
      ))}
    </ul>
  );
}

function DetectionListItem({
  detection, review, onAccept, onReject,
}: {
  detection: DetectionResponse;
  review?: ReviewState;
  onAccept?: (detectionId: string) => void;
  onReject?: (detectionId: string, reason: string) => void;
}) {
  const [showReasonInput, setShowReasonInput] = useState(false);
  const [reasonDraft, setReasonDraft] = useState("");
  const interactive = review !== undefined;

  return (
    <li className="detection-list__item">
      <div className="detection-list__header">
        <span className="detection-list__type">{detection.type}</span>
        <span className="detection-list__badge" style={{ backgroundColor: riskColor(detection.risk_level) }}>
          {riskLabel(detection.risk_level)}
        </span>
      </div>
      <div className="detection-list__meta">
        <span>處理方式：{detection.action}</span>
        <span>信心度：{detection.confidence.toFixed(2)}</span>
        <span>來源：自動偵測</span>
      </div>
      {detection.needs_review && <p className="detection-list__review">此項目需要人工確認</p>}

      {interactive && review && (
        <div className="detection-list__review-controls">
          <p className="detection-list__review-status">狀態：{STATUS_LABELS[review.status]}</p>
          {review.status === "REJECTED" && review.reason && (
            <p className="detection-list__reject-reason">原因：{review.reason}</p>
          )}
          {!showReasonInput && review.status === "PENDING" && (
            <div className="detection-list__actions">
              <button type="button" onClick={() => onAccept?.(detection.detection_id)}>
                ✓ 確認處理
              </button>
              <button type="button" onClick={() => setShowReasonInput(true)}>
                ✕ 誤判
              </button>
            </div>
          )}
          {showReasonInput && (
            <div className="detection-list__reason-form">
              <label htmlFor={`reason-${detection.detection_id}`}>請說明誤判原因</label>
              <input
                id={`reason-${detection.detection_id}`}
                type="text"
                value={reasonDraft}
                maxLength={200}
                onChange={(event) => setReasonDraft(event.target.value)}
              />
              <div className="detection-list__actions">
                <button
                  type="button"
                  disabled={reasonDraft.trim().length === 0}
                  onClick={() => {
                    onReject?.(detection.detection_id, reasonDraft.trim());
                    setShowReasonInput(false);
                    setReasonDraft("");
                  }}
                >
                  送出誤判原因
                </button>
                <button type="button" onClick={() => setShowReasonInput(false)}>
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
