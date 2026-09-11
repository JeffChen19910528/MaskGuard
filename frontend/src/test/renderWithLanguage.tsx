import { render, type RenderOptions, type RenderResult } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { LanguageProvider } from "../i18n/LanguageContext";
import { translations, type Locale } from "../i18n/translations";

/** Every component under test now reads translations via
 * `useLanguage()`, which requires a `<LanguageProvider>` ancestor — this
 * is the ONE helper test files should use instead of RTL's plain
 * `render()`. Defaults to `zh-TW` so existing assertions written against
 * the (formerly hardcoded) Traditional Chinese strings keep working
 * unchanged; pass `locale: "en"` to test the English strings instead. */
export function renderWithLanguage(ui: ReactElement, options?: RenderOptions & { locale?: Locale }): RenderResult {
  const { locale, ...renderOptions } = options ?? {};
  // Only overrides localStorage when a `locale` is explicitly given —
  // omitting it lets a PREVIOUSLY persisted choice (e.g. from an earlier
  // renderWithLanguage/unmount in the same test) actually survive across
  // a fresh mount, which is exactly the behavior real page reloads rely
  // on. `LanguageProvider` itself falls back to `zh-TW` when nothing is
  // stored at all (see its own `loadInitialLocale()`).
  if (locale !== undefined) {
    window.localStorage.setItem("maskguard.locale", locale);
  }
  const result = render(<LanguageProvider>{ui}</LanguageProvider>, renderOptions);
  // RTL's own `rerender(newUi)` replaces the root content with `newUi`
  // directly — it does NOT re-wrap in whatever the original `render()`
  // call wrapped, so every caller using `rerender` would otherwise lose
  // the `<LanguageProvider>` on the second render. Override it here so
  // `rerender` always re-wraps, exactly like the initial render did.
  return {
    ...result,
    rerender: (newUi: ReactNode) => result.rerender(<LanguageProvider>{newUi}</LanguageProvider>),
  };
}

export { translations };
