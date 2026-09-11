"""Phase 10.5: server-side, process-local rate limiting and abuse
protection — a control SEPARATE FROM AND ADDITIONAL TO the existing
`ConcurrencyLimiter` (concurrency.py, unchanged by this phase).

Rate limiting answers "how many requests may arrive within a time
window"; concurrency limiting answers "how many expensive operations may
execute simultaneously" (docs/rate-limit-implementation.md §3). Neither
replaces the other, and neither replaces body-size limits or image
validation (§4).

This module never touches PolicyEngine/RiskEngine/Detection/Redaction/
Verification/OCR, never stores raw request content, and fails OPEN on its
OWN internal errors (a broken rate limiter degrades availability of the
rate-limiting control itself, never authentication/authorization/
PolicyEngine/concurrency, which remain fully independent — see
`dependencies.py`'s `require_rate_limit`).

Process-local, in-memory, bounded state only (Phase 10.5 boundary — no
Redis, no distributed state; see docs/adr/ADR-006-rate-limiting.md).
"""
