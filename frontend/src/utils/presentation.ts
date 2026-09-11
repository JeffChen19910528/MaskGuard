/**
 * PRESENTATION ONLY (Phase 8.2 §10/§21): these maps decide what color/label
 * to draw for a risk level or status the BACKEND already assigned. They
 * must never be used to decide an action, mask, or redact anything — that
 * decision was already made by PolicyEngine before the frontend ever saw
 * this response. Every value here always ships with a paired text label,
 * so meaning is never color-only (accessibility, §23).
 */
import type { OverallStatus, RiskLevel } from "../api/types";

export const RISK_COLORS: Record<RiskLevel, string> = {
  CRITICAL: "#c62828", // strong red
  HIGH: "#ef6c00", // orange
  MEDIUM: "#f9a825", // yellow
  LOW: "#1565c0", // neutral blue
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  CRITICAL: "CRITICAL（極高風險）",
  HIGH: "HIGH（高風險）",
  MEDIUM: "MEDIUM（中風險）",
  LOW: "LOW（低風險）",
};

export const STATUS_LABELS: Record<OverallStatus, string> = {
  PASSED: "分析完成",
  NEEDS_REVIEW: "需要人工確認",
  BLOCKED: "已阻擋輸出",
  FAILED: "處理失敗",
  SKIPPED: "已略過驗證",
};

export function riskColor(level: RiskLevel): string {
  return RISK_COLORS[level] ?? RISK_COLORS.LOW;
}

export function riskLabel(level: RiskLevel): string {
  return RISK_LABELS[level] ?? level;
}

export function statusLabel(status: OverallStatus | string): string {
  return (STATUS_LABELS as Record<string, string>)[status] ?? status;
}
