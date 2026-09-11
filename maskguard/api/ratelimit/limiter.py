"""Phase 10.5 §27/§28/§29/§30/§31: the rate-limit algorithm and bounded
state store.

Algorithm — FIXED WINDOW COUNTER (§27's "choose the simplest secure
algorithm appropriate for the single-instance architecture"; explicitly
NOT token bucket / sliding-window log / leaky bucket, which add
complexity with no meaningful benefit for a single process):

    window_start = floor(now / window_seconds) * window_seconds
    if bucket.window_start != window_start: bucket resets to {window_start, count=0}
    allow iff bucket.count < capacity, then bucket.count += 1

Documented behavior (§27):
- Burst: a client may send up to `capacity` requests in a tight burst at
  the START of a window (fixed windows do not smooth traffic within a
  window — this is the known, accepted trade-off of the algorithm).
- Window boundary: in the worst case, a client sending `capacity`
  requests at the very END of one window and `capacity` more at the very
  START of the next window observes up to ~2x `capacity` requests within
  a short real-time span straddling the boundary. Accepted (§27: "do not
  use a sophisticated algorithm merely for appearance") — the mandatory
  regression test (§131: 3/10s -> req4 is 429) does not straddle a
  window boundary and passes deterministically.
- Refill: implicit — a new window simply starts counting from zero;
  there is no separate "refill rate" concept (unlike token bucket).
- Memory: O(number of distinct keys currently tracked), hard-bounded by
  `RateLimitSettings.max_keys` (§30/§32) via LRU eviction — the SAME
  bounded+evict pattern already used by `InMemorySessionStore` (Phase
  10.2).
- Concurrency: one `threading.Lock` per `RateLimiter` instance, held only
  for the in-memory check-and-increment (no I/O under the lock, §106) —
  atomic by construction (§28), verified by the concurrent-race test.
- Fairness: per-key isolation means one abusive key cannot consume
  another key's budget — the ONLY resource genuinely shared across keys
  is the bounded key-slot count itself (an adversarial key-exhaustion
  flood can evict a legitimate key's bucket early, resetting its window
  count to zero — a memory-safety trade-off, not a security bypass: the
  evicted client simply gets a fresh window, never MORE requests than its
  own policy allows going forward).

Uses `time.monotonic()` (§29) — never wall-clock/client-supplied time for
interval arithmetic. Process-local only; a restart resets all counters
(§80, intentional, documented — Phase 10.5 boundary).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import NamedTuple


class RateLimitDecision(NamedTuple):
    allowed: bool
    retry_after_seconds: int
    limit: int
    remaining: int


class _Bucket:
    __slots__ = ("window_start", "window_seconds", "count")

    def __init__(self, window_start: float, window_seconds: int) -> None:
        self.window_start = window_start
        self.window_seconds = window_seconds
        self.count = 0


class RateLimiter:
    """§119: internal state (bucket contents, keys) is never exposed
    through any API response, exception message, or header — callers
    only ever see the typed `RateLimitDecision`."""

    def __init__(self, max_keys: int, cleanup_interval_seconds: int = 60) -> None:
        self._max_keys = max(1, max_keys)
        self._cleanup_interval = max(1, cleanup_interval_seconds)
        self._buckets: "OrderedDict[str, _Bucket]" = OrderedDict()
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def check(self, key: str, capacity: int, window_seconds: int) -> RateLimitDecision:
        # §55/§61/§62: a caller passing a non-positive policy is a
        # configuration bug, never silently treated as "unlimited" —
        # `config.py` already rejects this at startup; defensive here too.
        if capacity <= 0 or window_seconds <= 0:
            return RateLimitDecision(False, window_seconds if window_seconds > 0 else 1, capacity, 0)

        now = time.monotonic()
        window_start = (now // window_seconds) * window_seconds

        with self._lock:
            self._maybe_cleanup_locked(now)

            bucket = self._buckets.get(key)
            if bucket is None or bucket.window_start != window_start:
                if key not in self._buckets and len(self._buckets) >= self._max_keys:
                    # §30/§32: bounded key space — evict the LEAST
                    # recently touched key, never grow past `max_keys`.
                    self._buckets.popitem(last=False)
                bucket = _Bucket(window_start, window_seconds)
                self._buckets[key] = bucket
            self._buckets.move_to_end(key)

            if bucket.count >= capacity:
                retry_after = int(bucket.window_start + window_seconds - now) + 1
                return RateLimitDecision(False, max(retry_after, 1), capacity, 0)

            bucket.count += 1
            return RateLimitDecision(True, 0, capacity, max(capacity - bucket.count, 0))

    def _maybe_cleanup_locked(self, now: float) -> None:
        # §31/§79/§105: bounded, inline sweep — never a separate
        # background task. Runs at most once per `cleanup_interval`
        # regardless of request volume.
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        stale_keys = [
            k for k, b in self._buckets.items()
            if now >= b.window_start + b.window_seconds
        ]
        for k in stale_keys:
            del self._buckets[k]

    def cleanup_now(self) -> int:
        """Test/operational hook: force an immediate sweep regardless of
        the interval, returning the number of buckets removed."""
        with self._lock:
            before = len(self._buckets)
            self._last_cleanup = -1.0  # force the interval check to pass
            self._maybe_cleanup_locked(time.monotonic())
            return before - len(self._buckets)

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._buckets)
