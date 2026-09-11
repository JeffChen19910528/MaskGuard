"""Phase 10.2 §7/§10/§11/§16: authorization-code-with-PKCE flow mechanics
and ID token validation. Provider-agnostic (§3) — nothing here branches on
a specific IdP; only standard OIDC/OAuth2 behavior.

Token exchange happens entirely server-side (§16) — this module is never
imported by, or exposed to, the frontend.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from .config import AuthSettings
from .discovery import JwksKeyProvider, OidcDiscoveryDocument
from .errors import AuthenticationFailedError, AuthProviderUnavailableError

#: §11: the ONLY algorithms this implementation will ever accept. `none`
#: is never in this list — PyJWT's own `algorithms=` parameter rejects
#: anything not explicitly named here, including `alg: none`, by design
#: (§74: relying on the maintained library's own safe-by-construction
#: behavior rather than a hand-rolled check).
_ALLOWED_ALGORITHMS = ("RS256", "ES256")


def generate_pkce_pair() -> tuple[str, str]:
    """§10/§75: PKCE S256 (never `plain` — no provider requirement has
    forced that fallback, so it is never offered). Verifier: 32
    cryptographically random bytes, URL-safe base64 (43 chars, within the
    RFC 7636 43-128 char range)."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)  # §8/§75


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)  # §9/§75


def build_authorization_url(
    discovery: OidcDiscoveryDocument, settings: AuthSettings, *, state: str, nonce: str, code_challenge: str
) -> str:
    """§7: Authorization Code flow only — `response_type=code`, never
    `token`/`id_token` (the implicit flow, explicitly forbidden by §7)."""
    params = {
        "response_type": "code",
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": " ".join(settings.scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{discovery.authorization_endpoint}?{urlencode(params)}"


async def exchange_code_for_tokens(
    discovery: OidcDiscoveryDocument,
    settings: AuthSettings,
    *,
    code: str,
    code_verifier: str,
    http_client: httpx.AsyncClient,
) -> dict:
    """§16: server-side only. §36/§37: the authorization code and any
    resulting token are never logged by this function or its caller."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.redirect_uri,
        "client_id": settings.client_id,
        "code_verifier": code_verifier,
    }
    if settings.client_secret:
        data["client_secret"] = settings.client_secret
    try:
        response = await http_client.post(discovery.token_endpoint, data=data)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthProviderUnavailableError() from exc


@dataclass(frozen=True)
class ValidatedIdTokenClaims:
    subject: str
    issuer: str
    email: str | None
    display_name: str | None


async def validate_id_token(
    id_token: str,
    *,
    discovery: OidcDiscoveryDocument,
    settings: AuthSettings,
    key_provider: JwksKeyProvider,
    expected_nonce: str,
) -> ValidatedIdTokenClaims:
    """§11: full cryptographic + semantic validation — never a bare
    `jwt.decode(..., options={"verify_signature": False})` or manual
    base64 decode (§95's own search list flags exactly that pattern as a
    forbidden bypass). Every one of §11's eight checks is performed:
    signature, issuer, audience, expiration, not-before, nonce, algorithm
    policy, required claims.
    """
    try:
        signing_key = await asyncio.to_thread(key_provider.get_signing_key, id_token)
    except (jwt.exceptions.PyJWKClientError, jwt.exceptions.InvalidTokenError) as exc:
        # §15/§55: an unrecognized/invalid key id — never trusted merely
        # because it appears in the token. `InvalidTokenError` also covers
        # a malformed token that fails even at the "read the header to
        # find kid" step, before signature verification is reached.
        raise AuthenticationFailedError() from exc

    try:
        claims = jwt.decode(
            id_token,
            key=signing_key.key,
            algorithms=list(_ALLOWED_ALGORITHMS),  # §11/§56: explicit allowlist, alg=none structurally rejected
            audience=settings.client_id,  # §13: PyJWT itself correctly handles a list-valued `aud` claim containing this value
            issuer=settings.issuer,  # §12
            leeway=settings.clock_skew_seconds,  # §14: applies to exp/iat/nbf
            options={
                "require": ["exp", "iat", "sub", "iss", "aud"],  # §11: required claims
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except jwt.exceptions.InvalidTokenError as exc:
        raise AuthenticationFailedError() from exc

    # §9: nonce is NOT a standard PyJWT-validated claim — checked explicitly.
    # Mismatch or absence: authentication FAILED, never silently ignored.
    if not expected_nonce or claims.get("nonce") != expected_nonce:
        raise AuthenticationFailedError()

    subject = claims.get("sub")
    issuer = claims.get("iss")
    if not subject or not issuer:
        raise AuthenticationFailedError()

    return ValidatedIdTokenClaims(
        subject=subject,
        issuer=issuer,
        email=claims.get("email"),
        display_name=claims.get("name"),
    )
