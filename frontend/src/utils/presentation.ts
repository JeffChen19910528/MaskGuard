/**
 * PRESENTATION ONLY (Phase 8.2 §10/§21): these maps decide what color/label
 * to draw for a risk level or status the BACKEND already assigned. They
 * must never be used to decide an action, mask, or redact anything — that
 * decision was already made by PolicyEngine before the frontend ever saw
 * this response. Every value here always ships with a paired text label,
 * so meaning is never color-only (accessibility, §23).
 *
 * `riskLabel`/`statusLabel` take the current `Translations` object (see
 * i18n/LanguageContext.tsx) so the DISPLAYED text follows the user's
 * chosen language — the underlying `RiskLevel`/`OverallStatus` values
 * themselves are never localized (they're the backend's own enum).
 */
import type { OverallStatus, RiskLevel } from "../api/types";
import type { Translations } from "../i18n/translations";

export const RISK_COLORS: Record<RiskLevel, string> = {
  CRITICAL: "#c62828", // strong red
  HIGH: "#ef6c00", // orange
  MEDIUM: "#f9a825", // yellow
  LOW: "#1565c0", // neutral blue
};

export function riskColor(level: RiskLevel): string {
  return RISK_COLORS[level] ?? RISK_COLORS.LOW;
}

export function riskLabel(level: RiskLevel, t: Translations): string {
  return t.presentation.risk[level] ?? level;
}

export function statusLabel(status: OverallStatus | string, t: Translations): string {
  return (t.presentation.status as Record<string, string>)[status] ?? status;
}
