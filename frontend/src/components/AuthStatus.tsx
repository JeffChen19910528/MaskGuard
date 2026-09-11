import { useEffect, useState } from "react";
import { getAuthStatus, logout, type AuthMeResponse } from "../api/client";

/**
 * Phase 10.2: minimal, additive authentication status indicator.
 *
 * - Never stores a token of any kind (no localStorage/sessionStorage/
 *   IndexedDB — the session lives in an HttpOnly cookie this component
 *   never reads).
 * - "Login" is a plain `<a href>` to `/api/v1/auth/login` — a full-page
 *   browser navigation (never a JS-driven fetch), exactly matching the
 *   server-side redirect-based OIDC flow (Phase 10.2 §7).
 * - When the deployment has no OIDC configured at all, `/api/v1/auth/me`
 *   doesn't exist and `getAuthStatus()` reports `authenticated: false` —
 *   indistinguishable here from "not logged in." That's fine: this
 *   component doesn't need to tell the two cases apart, since a "登入"
 *   link pointing at a route that also 404s is harmless (a deployment
 *   without OIDC never links anywhere real).
 */
export function AuthStatus() {
  const [status, setStatus] = useState<AuthMeResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAuthStatus().then((result) => {
      if (!cancelled) setStatus(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === null) {
    return null; // still loading — avoid a layout flash
  }

  if (status.authenticated) {
    const label = status.display_name || status.email || status.subject || "已登入";
    const permissions = status.permissions ?? [];
    // Phase 10.3 §39: UX-only signal derived from the backend's own
    // resolved permissions (never re-implemented client-side) — informs
    // the user their account has no review authority; every actual
    // review request is still independently enforced server-side
    // regardless of what this label shows (§39/§73).
    const canReview = permissions.some((p) => p.startsWith("review."));
    return (
      <div className="auth-status" aria-live="polite">
        <span className="auth-status__label">{label}</span>
        {!canReview && <span className="auth-status__note">（無審核權限）</span>}
        <button
          type="button"
          className="auth-status__logout"
          onClick={() => {
            void logout().then(() => setStatus({ authenticated: false }));
          }}
        >
          登出
        </button>
      </div>
    );
  }

  return (
    <div className="auth-status" aria-live="polite">
      <a className="auth-status__login" href="/api/v1/auth/login">
        登入
      </a>
    </div>
  );
}
