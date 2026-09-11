import { useLanguage } from "../i18n/LanguageContext";
import { LOCALES, type Locale } from "../i18n/translations";

/** A plain, accessible <select> — never client-side security state (it
 * only changes which text strings render; every actual security
 * decision remains server-side, unaffected by this control). */
export function LanguageSwitcher() {
  const { locale, setLocale } = useLanguage();

  return (
    <label className="language-switcher">
      <span className="language-switcher__label">🌐</span>
      <select
        aria-label="Language / 語言"
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {LOCALES.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
