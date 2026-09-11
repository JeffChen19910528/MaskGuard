"""Phase 10.2 §39/§41/§53: fail-closed production OIDC config validation +
in-memory session/transaction store bounding (§76/§77). Pure unit tests —
no Tesseract, no HTTP, no Docker.
"""
from __future__ import annotations

import time

import pytest

from maskguard.api.auth.config import AuthSettings, InsecureAuthConfigError, validate_production_auth_config
from maskguard.api.auth.models import AuthenticatedIdentity
from maskguard.api.auth.session import InMemoryPendingTransactionStore, InMemorySessionStore


def test_disabled_oidc_never_validated_even_in_production():
    settings = AuthSettings(oidc_enabled=False)
    validate_production_auth_config("production", settings)  # must not raise


def test_development_mode_never_requires_oidc_config():
    settings = AuthSettings(oidc_enabled=True)  # everything else left unset
    validate_production_auth_config("development", settings)  # must not raise


@pytest.mark.parametrize(
    "overrides",
    [
        {"issuer": None},
        {"client_id": None},
        {"redirect_uri": None},
        {"issuer": "http://idp.example.com"},  # not https
        {"redirect_uri": "http://maskguard.example.com/callback"},  # not https
        {"client_id": "changeme"},
        {"cookie_secure_override": False},
    ],
)
def test_production_mode_rejects_incomplete_or_insecure_config(overrides):
    base = dict(oidc_enabled=True, issuer="https://idp.example.com", client_id="real-client-id", redirect_uri="https://maskguard.example.com/api/v1/auth/callback")
    base.update(overrides)
    settings = AuthSettings(**base)
    with pytest.raises(InsecureAuthConfigError):
        validate_production_auth_config("production", settings)


def test_production_mode_accepts_complete_secure_config():
    settings = AuthSettings(
        oidc_enabled=True,
        issuer="https://idp.example.com",
        client_id="real-client-id",
        redirect_uri="https://maskguard.example.com/api/v1/auth/callback",
        cookie_secure_override=True,
    )
    validate_production_auth_config("production", settings)  # must not raise


def _identity(sub: str) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(subject=sub, issuer="https://idp.example.com", authenticated_at=time.time(), provider="oidc")


def test_session_store_bounded_evicts_oldest_when_full():
    store = InMemorySessionStore(max_sessions=3)
    first = store.create(_identity("a"), idle_timeout=3600, absolute_timeout=3600)
    store.create(_identity("b"), idle_timeout=3600, absolute_timeout=3600)
    store.create(_identity("c"), idle_timeout=3600, absolute_timeout=3600)
    store.create(_identity("d"), idle_timeout=3600, absolute_timeout=3600)  # forces eviction

    assert store.get(first.session_id, idle_timeout=3600) is None  # oldest evicted
    assert len(store._sessions) == 3


def test_session_store_expired_session_is_rejected():
    store = InMemorySessionStore(max_sessions=10)
    record = store.create(_identity("a"), idle_timeout=0, absolute_timeout=3600)
    time.sleep(0.01)
    assert store.get(record.session_id, idle_timeout=0) is None


def test_session_rotation_invalidates_old_id_and_mints_new_one():
    store = InMemorySessionStore(max_sessions=10)
    original = store.create(_identity("a"), idle_timeout=3600, absolute_timeout=3600)
    rotated = store.rotate(original.session_id, idle_timeout=3600, absolute_timeout=3600)
    assert rotated is not None
    assert rotated.session_id != original.session_id
    assert store.get(original.session_id, idle_timeout=3600) is None
    assert store.get(rotated.session_id, idle_timeout=3600) is not None


def test_pending_transaction_store_one_time_use():
    store = InMemoryPendingTransactionStore(max_transactions=10)
    txn = store.create(state="s", nonce="n", code_verifier="v", return_path="/")
    first = store.consume(txn.transaction_id, ttl_seconds=600)
    assert first is not None
    second = store.consume(txn.transaction_id, ttl_seconds=600)
    assert second is None  # replay rejected


def test_pending_transaction_store_bounded():
    store = InMemoryPendingTransactionStore(max_transactions=2)
    store.create(state="a", nonce="a", code_verifier="a", return_path="/")
    store.create(state="b", nonce="b", code_verifier="b", return_path="/")
    store.create(state="c", nonce="c", code_verifier="c", return_path="/")
    assert len(store._transactions) == 2
