/**
 * Manual-detection type dropdown (Phase 8.3 §11). This list is
 * PRESENTATION ONLY — it must be kept in sync BY HAND with the backend's
 * real allowlist (`maskguard/api/review_service.py::REVIEWABLE_MANUAL_TYPES`),
 * but the backend re-validates every submission regardless (§11: "Frontend
 * must never be authoritative") — sending a type not on the backend's own
 * list is rejected with `INVALID_DETECTION_TYPE` even if it were somehow
 * added here.
 */

export interface ManualTypeOption {
  value: string; // exact Core type string — must match the backend allowlist
  label: string; // Traditional Chinese display label
}

export const MANUAL_DETECTION_TYPES: ManualTypeOption[] = [
  { value: "TaiwanID", label: "身分證字號" },
  { value: "Passport", label: "護照號碼" },
  { value: "BankAccount", label: "銀行帳號" },
  { value: "CreditCard", label: "信用卡號" },
  { value: "SecretKeyValue", label: "密碼 / API 金鑰" },
  { value: "BearerToken", label: "存取權杖（Bearer Token）" },
  { value: "JWT", label: "JWT" },
  { value: "Email", label: "電子郵件" },
  { value: "Phone", label: "電話號碼" },
  { value: "PersonalName", label: "姓名" },
  { value: "Address", label: "地址" },
];
