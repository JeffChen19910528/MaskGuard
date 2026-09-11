"""Phase 10.2 §54: a deterministic, in-process mock OIDC provider for
tests — never a real Internet IdP dependency, never shipped anywhere near
production (this whole `tests/` tree is excluded from the Docker build
context by `.dockerignore`). Uses real RSA keys and real PyJWT signing so
the actual `maskguard.api.auth.oidc_client.validate_id_token` validation
logic runs unmodified against genuinely signed tokens.
"""
from __future__ import annotations

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm


class MockOidcProvider:
    def __init__(self, issuer: str = "https://idp.test.invalid") -> None:
        self.issuer = issuer
        self.authorization_endpoint = f"{issuer}/authorize"
        self.token_endpoint = f"{issuer}/token"
        self.jwks_uri = f"{issuer}/jwks"
        self._keys: dict[str, rsa.RSAPrivateKey] = {}
        self.add_key("key-1")

    def add_key(self, kid: str) -> str:
        self._keys[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return kid

    def discovery_document(self) -> dict:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": self.authorization_endpoint,
            "token_endpoint": self.token_endpoint,
            "jwks_uri": self.jwks_uri,
        }

    def jwks(self) -> dict:
        keys = []
        for kid, private_key in self._keys.items():
            jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
            jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
            keys.append(jwk)
        return {"keys": keys}

    def issue_id_token(
        self,
        *,
        subject: str = "user-123",
        audience: str = "maskguard-client",
        nonce: str | None = "test-nonce",
        issuer: str | None = None,
        kid: str = "key-1",
        alg: str = "RS256",
        expires_in: int = 300,
        not_before_offset: int = 0,
        issued_at_offset: int = 0,
        extra_claims: dict | None = None,
        omit_claims: tuple[str, ...] = (),
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": issuer if issuer is not None else self.issuer,
            "sub": subject,
            "aud": audience,
            "exp": now + expires_in,
            "iat": now + issued_at_offset,
            "nbf": now + not_before_offset,
        }
        if nonce is not None:
            claims["nonce"] = nonce
        if extra_claims:
            claims.update(extra_claims)
        for key in omit_claims:
            claims.pop(key, None)

        private_key = self._keys[kid]
        headers = {"kid": kid}
        return jwt.encode(claims, private_key, algorithm=alg, headers=headers)

    def issue_unsigned_none_alg_token(self, **kwargs) -> str:
        """§56: builds a header-and-payload-only `alg: none` token by hand
        (PyJWT's own `encode()` refuses to produce one) — used ONLY to
        prove the validator rejects it."""
        import base64
        import json

        now = int(time.time())
        header = {"alg": "none", "typ": "JWT"}
        payload = {"iss": self.issuer, "sub": "user-123", "aud": "maskguard-client", "exp": now + 300, "iat": now, "nonce": "test-nonce"}
        payload.update(kwargs)

        def b64(d: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

        return f"{b64(header)}.{b64(payload)}."


class FakeSigningKey:
    """Minimal stand-in for `jwt.PyJWK` — only the `.key` attribute
    `jwt.decode()` actually reads."""

    def __init__(self, key) -> None:
        self.key = key


class FakeKeyProvider:
    """Test double for `maskguard.api.auth.discovery.JwksKeyProvider` —
    returns the mock provider's OWN public key for a given `kid` instead
    of performing a real network fetch (§54's one deliberate seam; every
    other part of the flow — discovery, token exchange, JWT validation —
    exercises real code). Raises the same `PyJWKClientError` PyJWT itself
    raises for an unrecognized key id (§15/§55), so callers don't need to
    know this is a fake."""

    def __init__(self, provider: MockOidcProvider) -> None:
        self._provider = provider

    def get_signing_key(self, token: str) -> FakeSigningKey:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        private_key = self._provider._keys.get(kid)
        if private_key is None:
            raise jwt.exceptions.PyJWKClientError(f"Unable to find a signing key that matches: {kid!r}")
        return FakeSigningKey(private_key.public_key())
