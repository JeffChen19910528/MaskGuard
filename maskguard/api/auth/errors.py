"""Phase 10.2 §35: authentication errors use the SAME unified error
architecture as the rest of the API (`maskguard.api.errors.ApiError`) —
no separate error format introduced. Messages are safe, external, never
leak provider internals/JWT contents/signatures/secrets (§35).
"""
from __future__ import annotations

from fastapi import status

from ..errors import ApiError


class AuthenticationRequiredError(ApiError):
    """No valid session present (§30) — 401, never 403 (§30: "do not
    return 403 for authentication absence")."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTHENTICATION_REQUIRED"

    def __init__(self) -> None:
        super().__init__("Authentication is required for this request.")


class AuthenticationFailedError(ApiError):
    """Any OIDC validation failure — state/nonce/issuer/audience/
    signature/expiry/malformed-token/etc. (§27: "any failure: Authentication
    FAILED — do not partially create a session"). Deliberately a single
    generic external code/message regardless of WHICH check failed (§35:
    "avoid leaking whether a particular identity exists" / never leak
    provider internals) — the specific reason is logged server-side only
    (routes.py), tagged with request_id, never in the client-facing body."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTHENTICATION_FAILED"

    def __init__(self) -> None:
        super().__init__("Authentication failed.")


class SessionExpiredError(ApiError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "SESSION_EXPIRED"

    def __init__(self) -> None:
        super().__init__("Your session has expired. Please sign in again.")


class CsrfValidationError(ApiError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "CSRF_VALIDATION_FAILED"

    def __init__(self, message: str = "Request origin could not be verified.") -> None:
        super().__init__(message)


class OpenRedirectRejectedError(ApiError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "INVALID_RETURN_PATH"

    def __init__(self) -> None:
        super().__init__("The requested return path is not permitted.")


class AuthProviderUnavailableError(ApiError):
    """§60: the IdP is unreachable/misbehaving — distinct from a
    validation failure so operators can distinguish "provider outage"
    from "someone is attacking the login flow" in logs, while the
    CLIENT-facing response deliberately says no more than any other
    authentication failure (§35)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "AUTHENTICATION_FAILED"

    def __init__(self) -> None:
        super().__init__("Authentication failed.")
