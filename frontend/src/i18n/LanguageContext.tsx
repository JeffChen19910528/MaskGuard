import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { translations, type Locale, type Translations } from "./translations";

const STORAGE_KEY = "maskguard.locale";
const DEFAULT_LOCALE: Locale = "zh-TW";

function isLocale(value: unknown): value is Locale {
  return value === "zh-TW" || value === "en";
}

function loadInitialLocale(): Locale {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (isLocale(stored)) return stored;
  } catch {
    // localStorage can throw in private-browsing/locked-down contexts —
    // fall back to the default rather than crash the app over a
    // per-viewer convenience setting.
  }
  return DEFAULT_LOCALE;
}

interface LanguageContextValue {
  locale: Locale;
  t: Translations;
  setLocale: (locale: Locale) => void;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(loadInitialLocale);

  function setLocale(next: Locale) {
    setLocaleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Same as above — a failed write just means the choice won't
      // persist across reloads; never a reason to break the switch.
    }
  }

  const value = useMemo<LanguageContextValue>(
    () => ({ locale, t: translations[locale], setLocale }),
    [locale],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

/** The ONE way any component reads the current locale/translations —
 * never import `translations` directly outside this module. */
export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error("useLanguage() must be used within a <LanguageProvider>.");
  }
  return ctx;
}
