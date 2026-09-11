"""Phase 10.6 §21/§23/§24/§25/§29/§30/§75: `RedisReplayStore` — atomic
one-time consumption against a real Redis container."""
from __future__ import annotations

import threading

import pytest
import redis as redis_lib

from maskguard.api.review_token import RedisReplayStore, ReplayStoreUnavailableError


@pytest.fixture()
def store(redis_url, redis_namespace):
    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    return RedisReplayStore(client, redis_namespace)


def test_first_claim_succeeds_second_fails(store):
    assert store.try_consume("sig-1", ttl_seconds=60) is True
    assert store.try_consume("sig-1", ttl_seconds=60) is False


def test_different_fingerprints_independent(store):
    assert store.try_consume("sig-a", ttl_seconds=60) is True
    assert store.try_consume("sig-b", ttl_seconds=60) is True


def test_ttl_present_on_claim_key(store, redis_namespace):
    store.try_consume("sig-ttl", ttl_seconds=5)
    ttl = store._client.ttl(f"{redis_namespace}review:sig-ttl")
    assert 0 < ttl <= 5


def test_redis_failure_raises_never_treated_as_unused():
    broken_client = redis_lib.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.3, socket_timeout=0.3)
    store = RedisReplayStore(broken_client, "maskguard:test:")
    with pytest.raises(ReplayStoreUnavailableError):
        store.try_consume("sig-x", ttl_seconds=60)


@pytest.mark.parametrize("worker_count", [2, 4, 8, 16])
def test_concurrent_same_token_exactly_one_success(redis_url, redis_namespace, worker_count):
    """§23/§24/§25: MANDATORY — same valid token, many simultaneous
    requests (real threads, real Redis, real network round trips), must
    yield EXACTLY ONE success."""
    results = []
    lock = threading.Lock()

    def worker():
        client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
        store = RedisReplayStore(client, redis_namespace)
        ok = store.try_consume("shared-signature", ttl_seconds=60)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(worker_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1
    assert results.count(False) == worker_count - 1


def test_cross_instance_replay_detected(redis_url, redis_namespace):
    """§26/§63: token "generated on Node A, consumed on Node B" (same
    signature reaches two independently-constructed stores sharing one
    Redis) — the SECOND store correctly sees it as already used."""
    client_a = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    client_b = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    store_a = RedisReplayStore(client_a, redis_namespace)
    store_b = RedisReplayStore(client_b, redis_namespace)

    assert store_a.try_consume("cross-node-sig", ttl_seconds=60) is True
    assert store_b.try_consume("cross-node-sig", ttl_seconds=60) is False
