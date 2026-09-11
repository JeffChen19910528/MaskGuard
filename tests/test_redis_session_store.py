"""Phase 10.6 §7/§10/§11/§12/§13/§18/§81/§82: `RedisSessionStore`/
`RedisPendingTransactionStore` against a real Redis container."""
from __future__ import annotations

import time

import pytest
import redis as redis_lib

from maskguard.api.auth.models import AuthenticatedIdentity
from maskguard.api.auth.session import RedisPendingTransactionStore, RedisSessionStore
from maskguard.api.redisstate.client import RedisUnavailableError


def _identity(subject="user-1", issuer="https://idp.test") -> AuthenticatedIdentity:
    return AuthenticatedIdentity(subject=subject, issuer=issuer, authenticated_at=time.time(), provider="oidc")


@pytest.fixture()
def store(redis_url, redis_namespace):
    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    return RedisSessionStore(client, redis_namespace)


def test_create_then_get_roundtrip(store):
    record = store.create(_identity(), idle_timeout=300, absolute_timeout=3600)
    fetched = store.get(record.session_id, idle_timeout=300)
    assert fetched is not None
    assert fetched.identity.identity_key == record.identity.identity_key


def test_session_key_is_namespaced_not_by_email(store, redis_namespace):
    identity = _identity(subject="user-1", issuer="https://idp.test")
    identity = AuthenticatedIdentity(**{**identity.__dict__, "email": "user@example.com"})
    record = store.create(identity, idle_timeout=300, absolute_timeout=3600)
    raw_keys = list(store._client.scan_iter(f"{redis_namespace}session:*"))
    assert len(raw_keys) == 1
    assert "user@example.com" not in raw_keys[0]
    assert record.session_id in raw_keys[0]


def test_ttl_present_and_bounded_by_absolute_timeout(store):
    record = store.create(_identity(), idle_timeout=300, absolute_timeout=5)
    ttl = store._client.ttl(store._key(record.session_id))
    assert 0 < ttl <= 5


def test_delete_removes_key(store):
    record = store.create(_identity(), idle_timeout=300, absolute_timeout=3600)
    store.delete(record.session_id)
    assert store.get(record.session_id, idle_timeout=300) is None


def test_expired_by_absolute_timeout_is_unavailable(store):
    record = store.create(_identity(), idle_timeout=300, absolute_timeout=1)
    time.sleep(1.3)
    assert store.get(record.session_id, idle_timeout=300) is None


def test_rotate_invalidates_old_and_creates_new(store):
    record = store.create(_identity(), idle_timeout=300, absolute_timeout=3600)
    new_record = store.rotate(record.session_id, idle_timeout=300, absolute_timeout=3600)
    assert new_record is not None
    assert new_record.session_id != record.session_id
    assert store.get(record.session_id, idle_timeout=300) is None
    assert store.get(new_record.session_id, idle_timeout=300) is not None


def test_get_unknown_session_returns_none(store):
    assert store.get("does-not-exist", idle_timeout=300) is None


def test_get_corrupted_value_treated_as_absent_never_authenticated(store):
    key = f"{store._prefix}corrupted-id"
    store._client.set(key, "not-json-at-all", ex=60)
    assert store.get("corrupted-id", idle_timeout=300) is None


def test_redis_failure_raises_not_silently_anonymous():
    broken_client = redis_lib.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.3, socket_timeout=0.3)
    store = RedisSessionStore(broken_client, "maskguard:test:")
    with pytest.raises(RedisUnavailableError):
        store.get("any-session-id", idle_timeout=300)
    with pytest.raises(RedisUnavailableError):
        store.create(_identity(), idle_timeout=300, absolute_timeout=3600)


# --- Cross-instance simulation: two independent RedisSessionStore
# objects sharing the SAME underlying Redis (i.e. "Node A" / "Node B")
# must observe exactly the same state. ---------------------------------


def test_cross_instance_session_visible_on_second_store(redis_url, redis_namespace):
    client_a = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    client_b = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    store_a = RedisSessionStore(client_a, redis_namespace)
    store_b = RedisSessionStore(client_b, redis_namespace)

    record = store_a.create(_identity(), idle_timeout=300, absolute_timeout=3600)
    seen_on_b = store_b.get(record.session_id, idle_timeout=300)
    assert seen_on_b is not None
    assert seen_on_b.identity.identity_key == record.identity.identity_key


def test_cross_instance_logout_propagates(redis_url, redis_namespace):
    client_a = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    client_b = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    store_a = RedisSessionStore(client_a, redis_namespace)
    store_b = RedisSessionStore(client_b, redis_namespace)

    record = store_a.create(_identity(), idle_timeout=300, absolute_timeout=3600)
    assert store_b.get(record.session_id, idle_timeout=300) is not None
    store_b.delete(record.session_id)  # "logout" performed via Node B
    assert store_a.get(record.session_id, idle_timeout=300) is None  # Node A sees it gone too


class _FakeTxnAuthRuntimeSettings:
    pass


def test_transaction_store_one_time_consume(redis_url, redis_namespace):
    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    store = RedisPendingTransactionStore(client, redis_namespace)
    txn = store.create(state="s", nonce="n", code_verifier="v", return_path="/x")
    consumed = store.consume(txn.transaction_id, ttl_seconds=600)
    assert consumed is not None
    assert consumed.state == "s"
    replay = store.consume(txn.transaction_id, ttl_seconds=600)
    assert replay is None  # §79: one-time use, even across a fresh consume() call


def test_transaction_store_cross_instance(redis_url, redis_namespace):
    client_a = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    client_b = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    store_a = RedisPendingTransactionStore(client_a, redis_namespace)
    store_b = RedisPendingTransactionStore(client_b, redis_namespace)

    txn = store_a.create(state="s", nonce="n", code_verifier="v", return_path="/x")  # "login on Node A"
    consumed = store_b.consume(txn.transaction_id, ttl_seconds=600)  # "callback on Node B"
    assert consumed is not None
    assert consumed.transaction_id == txn.transaction_id
