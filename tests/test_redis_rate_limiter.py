"""Phase 10.6 §33/§34/§35/§36/§37/§38/§39/§83: `RedisRateLimiter` against
a real Redis container."""
from __future__ import annotations

import threading

import pytest
import redis as redis_lib

from maskguard.api.ratelimit.redis_limiter import RedisRateLimiter


@pytest.fixture()
def limiter(redis_url, redis_namespace):
    client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    return RedisRateLimiter(client, redis_namespace)


def test_allows_up_to_capacity_then_rejects(limiter):
    results = [limiter.check("k", capacity=3, window_seconds=10).allowed for _ in range(4)]
    assert results == [True, True, True, False]


def test_retry_after_positive_and_bounded(limiter):
    for _ in range(3):
        limiter.check("k", capacity=3, window_seconds=10)
    decision = limiter.check("k", capacity=3, window_seconds=10)
    assert decision.allowed is False
    assert 1 <= decision.retry_after_seconds <= 11


def test_different_keys_independent(limiter):
    for _ in range(3):
        assert limiter.check("a", capacity=3, window_seconds=10).allowed
    assert limiter.check("b", capacity=3, window_seconds=10).allowed


def test_ttl_present_on_counter_key(limiter, redis_namespace):
    limiter.check("ttl-key", capacity=5, window_seconds=5)
    keys = list(limiter._client.scan_iter(f"{redis_namespace}ratelimit:ttl-key:*"))
    assert len(keys) == 1
    ttl = limiter._client.ttl(keys[0])
    assert 0 < ttl <= 6


def test_window_reset_allows_new_requests(limiter):
    for _ in range(2):
        assert limiter.check("k", capacity=2, window_seconds=1).allowed
    assert limiter.check("k", capacity=2, window_seconds=1).allowed is False
    import time

    time.sleep(1.3)
    assert limiter.check("k", capacity=2, window_seconds=1).allowed is True


def test_non_positive_policy_never_allows(limiter):
    assert limiter.check("k", capacity=0, window_seconds=10).allowed is False
    assert limiter.check("k2", capacity=5, window_seconds=0).allowed is False


# --- MANDATORY: shared-counter atomicity across "nodes" ------------------


@pytest.mark.parametrize("worker_count", [2, 4, 8, 16])
def test_concurrent_race_does_not_exceed_capacity(redis_url, redis_namespace, worker_count):
    """§34/§35/§39: N concurrent workers (independent Redis connections,
    simulating independent API-node processes) against capacity=5 must
    accept EXACTLY 5, never more, due to Redis's own atomic INCR — not
    merely "close to 5.\""""
    accepted = []
    lock = threading.Lock()

    def worker():
        client = redis_lib.Redis.from_url(redis_url, decode_responses=True)
        limiter = RedisRateLimiter(client, redis_namespace)
        for _ in range(10):
            if limiter.check("shared-counter", capacity=5, window_seconds=30).allowed:
                with lock:
                    accepted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(worker_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(accepted) == 5


def test_cross_node_shared_limit_not_per_node(redis_url, redis_namespace):
    """§38: MANDATORY — limit=3; requests A->NodeA, B->NodeB, C->NodeA,
    D->NodeB against the SAME key must yield 3 allowed, 1 rejected total
    — never 3 allowed PER node (6 total)."""
    client_a = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    client_b = redis_lib.Redis.from_url(redis_url, decode_responses=True)
    node_a = RedisRateLimiter(client_a, redis_namespace)
    node_b = RedisRateLimiter(client_b, redis_namespace)

    outcomes = [
        node_a.check("shared", capacity=3, window_seconds=30).allowed,
        node_b.check("shared", capacity=3, window_seconds=30).allowed,
        node_a.check("shared", capacity=3, window_seconds=30).allowed,
        node_b.check("shared", capacity=3, window_seconds=30).allowed,
    ]
    assert outcomes == [True, True, True, False]
