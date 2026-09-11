/**
 * Manual-detection type dropdown (Phase 8.3 §11). This list is
 * PRESENTATION ONLY — it must be kept in sync BY HAND with the backend's
 * real allowlist (`maskguard/api/review_service.py::REVIEWABLE_MANUAL_TYPES`),
 * but the backend re-validates every submission regardless (§11: "Frontend
 * must never be authoritative") — sending a type not on the backend's own
 * list is rejected with `INVALID_DETECTION_TYPE` even if it were somehow
 * added here.
 *
 * Only the VALUE list is defined here (the exact Core type string, never
 * localized) — the display label is looked up from the current
 * `Translations.manualTypes` (i18n/translations.ts) so it follows the
 * user's chosen language.
 */
import type { Translations } from "../i18n/translations";

export interface ManualTypeOption {
  value: string; // exact Core type string — must match the backend allowlist
  label: string;
}

export const MANUAL_DETECTION_TYPE_VALUES: string[] = [
  "TaiwanID",
  "Passport",
  "BankAccount",
  "CreditCard",
  "SecretKeyValue",
  "BearerToken",
  "JWT",
  "Email",
  "Phone",
  "PersonalName",
  "Address",
];

export function manualDetectionTypeLabel(value: string, t: Translations): string {
  return t.manualTypes[value] ?? value;
}

export function manualDetectionTypeOptions(t: Translations): ManualTypeOption[] {
  return MANUAL_DETECTION_TYPE_VALUES.map((value) => ({ value, label: manualDetectionTypeLabel(value, t) }));
}
