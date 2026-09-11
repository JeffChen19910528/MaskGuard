"""Phase 10.6: shared distributed state for multi-instance MaskGuard
deployments — session state (`auth/session.py`), review-token replay
protection (`review_token.py`), and rate-limit counters
(`ratelimit/redis_limiter.py`) each gain a Redis-backed implementation
of their EXISTING abstraction, selected at construction time when
`REDIS_ENABLED=true`.

Redis is STATE, never AUTHORITY (§4 of the phase brief): it never makes
an authentication, authorization, or policy decision — it only stores
what those decisions already produced (a session record, a "this token
was consumed" marker, a request counter). OIDC remains the identity
source, Phase 10.3 remains the authorization source, PolicyEngine remains
the policy source.

`REDIS_ENABLED=false` (the default) is a complete no-op — every
component keeps its EXACT Phase 10.2/10.3/10.5 in-memory, process-local
behavior. This module introduces NO behavior change for a
single-instance deployment that hasn't opted in.
"""
