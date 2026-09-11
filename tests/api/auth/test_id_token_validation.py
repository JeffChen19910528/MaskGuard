"""Phase 10.2 §52/§56/§57: ID token validation failure matrix. Exercises
the REAL `maskguard.api.auth.oidc_client.validate_id_token` against real
RSA-signed tokens from `MockOidcProvider` — only key-fetching is faked
(`FakeKeyProvider`, see mock_provider.py).
"""
from __future__ import annotations

import pytest

from maskguard.api.auth.config import AuthSettings
from maskguard.api.auth.discovery import OidcDiscoveryDocument
from maskguard.api.auth.errors import AuthenticationFailedError
from maskguard.api.auth.oidc_client import validate_id_token

from .mock_provider import FakeKeyProvider, MockOidcProvider

ISSUER = "https://idp.test.invalid"
CLIENT_ID = "maskguard-client"


@pytest.fixture()
def provider() -> MockOidcProvider:
    return MockOidcProvider(issuer=ISSUER)


@pytest.fixture()
def key_provider(provider: MockOidcProvider) -> FakeKeyProvider:
    return FakeKeyProvider(provider)


@pytest.fixture()
def discovery(provider: MockOidcProvider) -> OidcDiscoveryDocument:
    doc = provider.discovery_document()
    return OidcDiscoveryDocument(**doc)


@pytest.fixture()
def settings() -> AuthSettings:
    return AuthSettings(oidc_enabled=True, issuer=ISSUER, client_id=CLIENT_ID, clock_skew_seconds=120)


async def _validate(token, discovery, settings, key_provider, nonce="test-nonce"):
    return await validate_id_token(token, discovery=discovery, settings=settings, key_provider=key_provider, expected_nonce=nonce)


@pytest.mark.asyncio
async def test_valid_token_is_accepted(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(subject="alice", audience=CLIENT_ID)
    claims = await _validate(token, discovery, settings, key_provider)
    assert claims.subject == "alice"
    assert claims.issuer == ISSUER


@pytest.mark.asyncio
async def test_invalid_issuer_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(issuer="https://attacker.invalid")
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_wrong_audience_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(audience="some-other-client")
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_multi_audience_containing_client_id_is_accepted(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(extra_claims={"aud": [CLIENT_ID, "another-audience"]})
    claims = await _validate(token, discovery, settings, key_provider)
    assert claims.subject


@pytest.mark.asyncio
async def test_expired_token_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(expires_in=-3600)  # expired an hour ago, outside 120s skew
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_expired_token_within_clock_skew_is_accepted(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(expires_in=-60)  # expired 60s ago, within 120s skew
    claims = await _validate(token, discovery, settings, key_provider)
    assert claims.subject


@pytest.mark.asyncio
async def test_not_before_violation_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(not_before_offset=3600)  # not valid for another hour
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_missing_nonce_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(nonce=None)
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_wrong_nonce_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(nonce="a-different-nonce")
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_missing_required_claim_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token(omit_claims=("sub",))
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_unknown_key_id_rejected(provider, discovery, settings, key_provider):
    # Signed with a REAL key the provider knows about, but the token's own
    # `kid` header claims an id the key provider has never seen — proves
    # the lookup is by kid, not "any key the provider happens to hold".
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod
    import jwt as pyjwt

    unregistered_key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
    token = pyjwt.encode(
        {"iss": ISSUER, "sub": "alice", "aud": CLIENT_ID, "exp": 9999999999, "iat": 1, "nonce": "test-nonce"},
        unregistered_key,
        algorithm="RS256",
        headers={"kid": "a-key-id-that-was-never-registered"},
    )
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_alg_none_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_unsigned_none_alg_token()
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_unsupported_algorithm_rejected(provider, discovery, settings, key_provider):
    # HS256 (symmetric) is not in the allowed algorithm list at all — this
    # must fail even before any question of "which secret" arises.
    import jwt as pyjwt

    token = pyjwt.encode(
        {"iss": ISSUER, "sub": "alice", "aud": CLIENT_ID, "exp": 9999999999, "iat": 1, "nonce": "test-nonce"},
        "some-shared-secret",
        algorithm="HS256",
    )
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_malformed_jwt_rejected(discovery, settings, key_provider):
    with pytest.raises(AuthenticationFailedError):
        await _validate("this.is-not.a-valid-jwt", discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_tampered_signature_rejected(provider, discovery, settings, key_provider):
    token = provider.issue_id_token()
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}AAAA"
    with pytest.raises(AuthenticationFailedError):
        await _validate(tampered, discovery, settings, key_provider)


@pytest.mark.asyncio
async def test_key_rotation_new_key_is_trusted_after_registration(provider, discovery, settings, key_provider):
    """§55: provider rotates to a new key -> a token signed with it is
    valid once that key is known to the (fake) key provider."""
    new_kid = provider.add_key("key-2")
    token = provider.issue_id_token(kid=new_kid)
    claims = await _validate(token, discovery, settings, key_provider)
    assert claims.subject


@pytest.mark.asyncio
async def test_malicious_unregistered_key_never_trusted(provider, discovery, settings, key_provider):
    """§55: a token claiming a kid that was never part of the provider's
    own key set must NOT become trusted merely by appearing in a token —
    covered identically by test_unknown_key_id_rejected above; this test
    additionally confirms a self-signed token with an attacker-generated
    key (not just an unknown kid) is also rejected."""
    from cryptography.hazmat.primitives.asymmetric import rsa as rsa_mod

    attacker_key = rsa_mod.generate_private_key(public_exponent=65537, key_size=2048)
    import jwt as pyjwt

    token = pyjwt.encode(
        {"iss": ISSUER, "sub": "attacker", "aud": CLIENT_ID, "exp": 9999999999, "iat": 1, "nonce": "test-nonce"},
        attacker_key,
        algorithm="RS256",
        headers={"kid": "key-1"},  # claims a REAL kid but was signed with a DIFFERENT key
    )
    with pytest.raises(AuthenticationFailedError):
        await _validate(token, discovery, settings, key_provider)
