"""Phase 10.2 §6/§15/§58/§59: standards-based OIDC discovery + JWKS.

SSRF safety (§58): the ONLY URL ever fetched here is derived from the
server-side CONFIGURED `issuer` (`AuthSettings.issuer`, an operator-set
environment value — never a request, header, cookie, or token claim).
Nothing in this module accepts a URL from an untrusted source. The
discovery document's own `issuer`/`jwks_uri` fields are used ONLY after
being validated against that same configured issuer (see
`fetch_discovery_document`) — a malicious or misconfigured discovery
response cannot redirect JWKS fetching to an attacker-chosen host, because
`jwks_uri` is checked to share the issuer's own origin before use.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import jwt

from .config import AuthSettings
from .errors import AuthProviderUnavailableError


@dataclass(frozen=True)
class OidcDiscoveryDocument:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


async def fetch_discovery_document(settings: AuthSettings, http_client: httpx.AsyncClient) -> OidcDiscoveryDocument:
    """§6: fetches `<issuer>/.well-known/openid-configuration` and
    validates the required fields are present and that the document's own
    `issuer` matches the configured, trusted issuer exactly (§12 — never
    trust a document that claims to be a different issuer than what was
    configured) and that `jwks_uri`/`authorization_endpoint`/
    `token_endpoint` share the issuer's origin (§58 SSRF hardening —
    a discovery response cannot redirect key/token fetching off-origin)."""
    if not settings.issuer:
        raise AuthProviderUnavailableError()
    discovery_url = settings.issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        response = await http_client.get(discovery_url)
        response.raise_for_status()
        doc = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthProviderUnavailableError() from exc

    issuer = doc.get("issuer")
    authorization_endpoint = doc.get("authorization_endpoint")
    token_endpoint = doc.get("token_endpoint")
    jwks_uri = doc.get("jwks_uri")
    if not all([issuer, authorization_endpoint, token_endpoint, jwks_uri]):
        raise AuthProviderUnavailableError()
    if issuer != settings.issuer:
        raise AuthProviderUnavailableError()
    for endpoint in (authorization_endpoint, token_endpoint, jwks_uri):
        if not _same_origin(endpoint, settings.issuer):
            raise AuthProviderUnavailableError()

    return OidcDiscoveryDocument(
        issuer=issuer,
        authorization_endpoint=authorization_endpoint,
        token_endpoint=token_endpoint,
        jwks_uri=jwks_uri,
    )


class JwksKeyProvider:
    """§15: thin wrapper over PyJWT's own maintained `PyJWKClient` — never
    a hand-rolled JWKS fetch/cache/key-selection implementation (§74).
    `PyJWKClient` caches fetched keys and re-fetches automatically when an
    unrecognized `kid` is requested, bounded by its own internal
    least-recently-used cache size — this wrapper adds nothing beyond
    constructing it against the discovery-validated `jwks_uri`."""

    def __init__(self, jwks_uri: str, *, timeout_seconds: float = 5.0, cache_lifespan_seconds: float = 300.0) -> None:
        # §59: bounded timeout, never PyJWKClient's generous 30s default.
        # Synchronous under the hood (PyJWKClient uses urllib, not the
        # shared httpx.AsyncClient) — callers run this via
        # `asyncio.to_thread` (oidc_client.py) so a slow/unavailable JWKS
        # endpoint never blocks the event loop; acceptable given this call
        # is cache-hit in the overwhelming majority of requests (§15).
        self._client = jwt.PyJWKClient(
            jwks_uri, cache_keys=True, max_cached_keys=16, lifespan=cache_lifespan_seconds, timeout=timeout_seconds
        )

    def get_signing_key(self, token: str):
        return self._client.get_signing_key_from_jwt(token)
