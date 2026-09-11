"""Phase 10.6 §33/§34/§35/§36/§37/§43/§84: the Redis-backed rate-limit
backend — SAME fixed-window semantics as Phase 10.5's `RateLimiter`
(§36: "do not silently switch to token bucket"), SAME
`RateLimitDecision` return shape, just shared across every API instance.

Atomicity (§34/§35): a single, minimal, versioned Lua script (§84) does
INCR + conditional EXPIRE + capacity comparison in ONE round trip — never
`GET` then `SET` (§24/§35's own explicit warning against that race).
Window boundary is computed from REDIS's OWN clock (`TIME`), never a
node's local wall clock (§29/§83: "do not trust client time" — this also
means every node agrees on the exact same window even if their local
clocks have drifted from each other).

Memory bound (§43): every counter key carries its own `EXPIRE` (window
length + 1s) — an abandoned/one-off key is reclaimed by Redis itself,
without needing an LRU-eviction structure like the in-memory backend's
(that data structure was needed there specifically because in-memory
state has no built-in expiry; Redis's TTL IS the bound here).
"""
from __future__ import annotations

from .limiter import RateLimitDecision

#: §84: minimal, versioned (v1), no user input is ever embedded as
#: executable script content — `KEYS`/`ARGV` are the only inputs, both
#: passed through the Redis client's own parameterized script-call API.
_FIXED_WINDOW_SCRIPT_V1 = """
local capacity = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local time = redis.call('TIME')
local now = tonumber(time[1])
local window_start = now - (now % window)
local key = KEYS[1] .. ':' .. window_start
local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, window + 1)
end
if count > capacity then
    local ttl = redis.call('TTL', key)
    if ttl < 1 then
        ttl = window
    end
    return {0, ttl, capacity, 0}
end
return {1, 0, capacity, capacity - count}
"""


class RedisRateLimiter:
    def __init__(self, client, namespace: str) -> None:
        self._client = client
        self._prefix = f"{namespace}ratelimit:"
        self._script = client.register_script(_FIXED_WINDOW_SCRIPT_V1)

    def check(self, key: str, capacity: int, window_seconds: int) -> RateLimitDecision:
        from ..redisstate.client import safe_call

        if capacity <= 0 or window_seconds <= 0:
            return RateLimitDecision(False, window_seconds if window_seconds > 0 else 1, capacity, 0)

        allowed, retry_after, limit, remaining = safe_call(
            "ratelimit_check", self._script,
            keys=[self._prefix + key], args=[capacity, window_seconds],
        )
        return RateLimitDecision(bool(allowed), int(retry_after), int(limit), int(remaining))
