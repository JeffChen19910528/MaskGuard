"""Phase 10.5 §27/§28/§30/§31/§74/§77/§78/§79/§82: unit tests for the
rate-limit algorithm/state store itself — no HTTP, no Tesseract. Pure
logic tests, same class as tests/test_audit_storage.py.
"""
from __future__ import annotations

import threading
import time

from maskguard.api.ratelimit.limiter import RateLimiter


def test_allows_up_to_capacity_then_rejects():
    limiter = RateLimiter(max_keys=100)
    results = [limiter.check("k", capacity=3, window_seconds=10).allowed for _ in range(4)]
    assert results == [True, True, True, False]


def test_retry_after_is_positive_and_bounded():
    limiter = RateLimiter(max_keys=100)
    for _ in range(3):
        limiter.check("k", capacity=3, window_seconds=10)
    decision = limiter.check("k", capacity=3, window_seconds=10)
    assert decision.allowed is False
    assert 1 <= decision.retry_after_seconds <= 10


def test_different_keys_are_independent():
    limiter = RateLimiter(max_keys=100)
    for _ in range(3):
        assert limiter.check("a", capacity=3, window_seconds=10).allowed
    # "b" has its own fresh bucket — unaffected by "a"'s exhaustion.
    assert limiter.check("b", capacity=3, window_seconds=10).allowed


def test_window_reset_allows_new_requests():
    limiter = RateLimiter(max_keys=100)
    for _ in range(2):
        assert limiter.check("k", capacity=2, window_seconds=1).allowed
    assert limiter.check("k", capacity=2, window_seconds=1).allowed is False
    time.sleep(1.1)
    assert limiter.check("k", capacity=2, window_seconds=1).allowed is True


def test_non_positive_policy_never_allows():
    # §61/§62: 0 or negative is never "unlimited."
    limiter = RateLimiter(max_keys=100)
    assert limiter.check("k", capacity=0, window_seconds=10).allowed is False
    assert limiter.check("k2", capacity=5, window_seconds=0).allowed is False


def test_memory_bounded_by_max_keys():
    # §30/§32/§78/§135: many unique attacker-controlled keys must never
    # exceed max_keys buckets.
    limiter = RateLimiter(max_keys=50)
    for i in range(5000):
        limiter.check(f"attacker-key-{i}", capacity=5, window_seconds=60)
    assert limiter.key_count <= 50


def test_lru_eviction_does_not_crash_and_bounds_state():
    limiter = RateLimiter(max_keys=10)
    for i in range(1000):
        decision = limiter.check(f"k{i}", capacity=1, window_seconds=60)
        assert decision.allowed is True  # fresh key each time -> always the first hit
    assert limiter.key_count <= 10


def test_concurrent_race_does_not_exceed_capacity():
    # §28/§77: 4 threads * 50 requests against capacity=5 must accept
    # AT MOST 5 — atomicity under real concurrent access, not just
    # single-threaded logic.
    limiter = RateLimiter(max_keys=100)
    accepted = []
    lock = threading.Lock()

    def worker():
        for _ in range(50):
            decision = limiter.check("shared", capacity=5, window_seconds=30)
            if decision.allowed:
                with lock:
                    accepted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(accepted) == 5


def test_cleanup_removes_stale_entries():
    limiter = RateLimiter(max_keys=1000, cleanup_interval_seconds=60)
    for i in range(20):
        limiter.check(f"stale-{i}", capacity=5, window_seconds=1)
    time.sleep(1.2)
    removed = limiter.cleanup_now()
    assert removed == 20
    assert limiter.key_count == 0


def test_key_count_reflects_active_buckets():
    limiter = RateLimiter(max_keys=1000)
    limiter.check("a", capacity=5, window_seconds=60)
    limiter.check("b", capacity=5, window_seconds=60)
    assert limiter.key_count == 2
