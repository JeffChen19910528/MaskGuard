import type { DetectionResponse, SummaryResponse } from "../api/types";
import { statusLabel } from "../utils/presentation";

interface StatusBannerProps {
  status: string;
  summary: SummaryResponse;
  detections: DetectionResponse[];
}

/**
 * Displays the backend's OWN status/summary verbatim (relabeled to
 * Traditional Chinese for display only — see utils/presentation.ts). Never
 * reinterprets or recomputes a security status (Phase 8.2 §13).
 *
 * The per-level (High/Medium/Low) counts below are a plain presentation
 * COUNT over the `risk_level` label the backend already assigned each
 * detection — not a new classification. `critical_count`/`total_detections`
 * still come straight from the backend's own `summary` object.
 */
export function StatusBanner({ status, summary, detections }: StatusBannerProps) {
  const tone = status === "BLOCKED" || status === "FAILED" ? "danger" : status === "NEEDS_REVIEW" ? "warning" : "ok";
  const highCount = detections.filter((d) => d.risk_level === "HIGH").length;
  const mediumCount = detections.filter((d) => d.risk_level === "MEDIUM").length;
  const lowCount = detections.filter((d) => d.risk_level === "LOW").length;

  return (
    <div className={`status-banner status-banner--${tone}`} role="status" aria-live="polite">
      <p className="status-banner__status">狀態：{statusLabel(status)}</p>
      <dl className="status-banner__summary">
        <div>
          <dt>偵測項目</dt>
          <dd data-testid="count-total">{summary.total_detections}</dd>
        </div>
        <div>
          <dt>Critical</dt>
          <dd data-testid="count-critical">{summary.critical_count}</dd>
        </div>
        <div>
          <dt>High</dt>
          <dd data-testid="count-high">{highCount}</dd>
        </div>
        <div>
          <dt>Medium</dt>
          <dd data-testid="count-medium">{mediumCount}</dd>
        </div>
        <div>
          <dt>Low</dt>
          <dd data-testid="count-low">{lowCount}</dd>
        </div>
        <div>
          <dt>需人工確認</dt>
          <dd data-testid="count-needs-review">{summary.needs_review_count}</dd>
        </div>
      </dl>
    </div>
  );
}
