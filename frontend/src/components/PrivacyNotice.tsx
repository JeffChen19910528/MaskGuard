import { useLanguage } from "../i18n/LanguageContext";

/**
 * Privacy notice (§24). Wording deliberately matches what Phase 8.1's
 * backend actually guarantees (stateless, temp-file processing with
 * cleanup on every exit path — see maskguard/api/service.py) — never
 * claims a guarantee the architecture doesn't provide, in either
 * language (see i18n/translations.ts).
 */
export function PrivacyNotice() {
  const { t } = useLanguage();
  return <p className="privacy-notice">{t.privacy.notice}</p>;
}
