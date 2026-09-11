"""Phase 10.5 §55-64: rate-limit configuration. Same env-driven pattern as
`maskguard/api/audit/config.py` — no duplicate configuration system, no
hot reload (§109 — policies load once at startup; changing them requires
a restart, documented).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from ..auth.config import _bool_env
from ..config import _int_env

#: §11: explicit endpoint classes. Each maps 1:1 to a `RateLimitPolicy`
#: below — deliberately NOT one limit for every endpoint (§11).
AUTH = "AUTH"
READ = "READ"
IMAGE_ANALYZE = "IMAGE_ANALYZE"
IMAGE_REDACT = "IMAGE_REDACT"
IMAGE_VERIFY = "IMAGE_VERIFY"
REVIEW = "REVIEW"
AUDIT_QUERY = "AUDIT_QUERY"

ALL_CLASSES = frozenset({AUTH, READ, IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY, REVIEW, AUDIT_QUERY})

#: §9/§65: classes where an authenticated caller is checked against BOTH
#: an identity-scoped limit (narrow) AND a coarser client(IP)-scoped
#: limit (layered protection) — "do not over-engineer" (§9) is why AUTH
#: (no identity exists yet) and READ (`/auth/me`, cheap, low-risk polling)
#: are NOT layered: a single key is enough there.
_LAYERED_CLASSES = frozenset({IMAGE_ANALYZE, IMAGE_REDACT, IMAGE_VERIFY, REVIEW, AUDIT_QUERY})


class InsecureRateLimitConfigError(RuntimeError):
    """§55/§60: fail closed at startup on malformed rate-limit
    configuration — never a silent fallback to unlimited."""


@dataclass(frozen=True)
class RateLimitPolicy:
    #: §57: requests allowed per window — explicit units, never a bare
    #: ambiguous number.
    capacity: int
    window_seconds: int


def _policy(prefix: str, default_capacity: int, default_window: int) -> RateLimitPolicy:
    return RateLimitPolicy(
        capacity=_int_env(f"RATE_LIMIT_{prefix}_CAPACITY", default_capacity),
        window_seconds=_int_env(f"RATE_LIMIT_{prefix}_WINDOW_SECONDS", default_window),
    )


@dataclass(frozen=True)
class RateLimitSettings:
    #: §0/§56: master switch — same opt-in pattern as AUDIT_ENABLED/
    #: OIDC_ENABLED. False = zero behavior change from every prior phase.
    enabled: bool = field(default_factory=lambda: _bool_env("RATE_LIMIT_ENABLED", False))

    # §58: conservative-but-usable defaults, sized from realistic
    # browser/API scenarios (docs/rate-limit-implementation.md §8) —
    # never "RATE_LIMIT=10" with unstated units (§57).
    auth: RateLimitPolicy = field(default_factory=lambda: _policy("AUTH", 20, 60))
    read: RateLimitPolicy = field(default_factory=lambda: _policy("READ", 60, 60))
    image_analyze: RateLimitPolicy = field(default_factory=lambda: _policy("IMAGE_ANALYZE", 20, 60))
    image_redact: RateLimitPolicy = field(default_factory=lambda: _policy("IMAGE_REDACT", 20, 60))
    image_verify: RateLimitPolicy = field(default_factory=lambda: _policy("IMAGE_VERIFY", 30, 60))
    review: RateLimitPolicy = field(default_factory=lambda: _policy("REVIEW", 30, 60))
    audit_query: RateLimitPolicy = field(default_factory=lambda: _policy("AUDIT_QUERY", 30, 60))

    #: §9/§65: the coarser client(IP)-scoped bucket's capacity is this
    #: multiplier times the identity-scoped policy's own capacity (same
    #: window) — bounds "many identities behind one IP" without punishing
    #: legitimate shared egress (NAT/corporate proxy) as hard as a single
    #: per-identity ceiling would.
    client_multiplier: int = field(default_factory=lambda: _int_env("RATE_LIMIT_CLIENT_MULTIPLIER", 5))

    #: §30/§32: bounded key-space — an attacker generating unlimited
    #: unique keys (spoofed IPs, header floods) cannot grow memory past
    #: this many buckets; oldest-touched key is evicted first (LRU, same
    #: policy as `InMemorySessionStore`/`InMemoryPendingTransactionStore`,
    #: Phase 10.2).
    max_keys: int = field(default_factory=lambda: _int_env("RATE_LIMIT_MAX_KEYS", 50_000))

    #: §31/§105: bounded periodic sweep of stale buckets, run inline on an
    #: occasional `check()` call — never a separate background task.
    cleanup_interval_seconds: int = field(default_factory=lambda: _int_env("RATE_LIMIT_CLEANUP_INTERVAL_SECONDS", 60))

    #: §8/§43/§118: `X-Real-IP` is trusted ONLY when this is true. Set to
    #: true in docker-compose*.yml, where Nginx is the verified SOLE
    #: ingress (the `api` service publishes no host port — see
    #: docker-compose.yml) and unconditionally OVERWRITES `X-Real-IP`
    #: with `$remote_addr` (frontend/nginx/common.conf.inc) — a client
    #: cannot make this header carry anything but Nginx's own view of the
    #: TCP peer. False by default (direct/dev/test deployments, where the
    #: ASGI-level `request.client.host` — the actual TCP peer — is used
    #: instead). `X-Forwarded-For` is NEVER read (§6/§8): it is a
    #: client-appendable list, materially less trustworthy than a header
    #: a reverse proxy always overwrites outright.
    trust_proxy_headers: bool = field(default_factory=lambda: _bool_env("RATE_LIMIT_TRUST_PROXY_HEADERS", False))

    def policy_for(self, rate_class: str) -> RateLimitPolicy:
        return {
            AUTH: self.auth,
            READ: self.read,
            IMAGE_ANALYZE: self.image_analyze,
            IMAGE_REDACT: self.image_redact,
            IMAGE_VERIFY: self.image_verify,
            REVIEW: self.review,
            AUDIT_QUERY: self.audit_query,
        }[rate_class]

    def is_layered(self, rate_class: str) -> bool:
        return rate_class in _LAYERED_CLASSES


@lru_cache
def get_rate_limit_settings() -> RateLimitSettings:
    return RateLimitSettings()


def _validate_policy(name: str, policy: RateLimitPolicy) -> None:
    # §60/§61/§62: zero/negative is REJECTED, never interpreted as
    # "unlimited" — malformed configuration must fail safely, not
    # silently disable the control.
    if policy.capacity <= 0:
        raise InsecureRateLimitConfigError(f"RATE_LIMIT_{name}_CAPACITY must be a positive integer.")
    if policy.window_seconds <= 0:
        raise InsecureRateLimitConfigError(f"RATE_LIMIT_{name}_WINDOW_SECONDS must be a positive integer.")


def validate_production_rate_limit_config(environment: str, settings: RateLimitSettings) -> None:
    """§55/§60/§79: fail closed at startup — never lazily on first
    request. §59: production is NOT force-enabled by default (the same
    disclosed opt-in pattern OIDC_ENABLED/AUDIT_ENABLED already use — see
    docs/rate-limit-implementation.md "Production configuration" for the
    explicit operator-facing warning this represents), but whatever
    configuration IS supplied is validated strictly, in every
    environment, not just when `enabled`."""
    for name, policy in (
        ("AUTH", settings.auth), ("READ", settings.read),
        ("IMAGE_ANALYZE", settings.image_analyze), ("IMAGE_REDACT", settings.image_redact),
        ("IMAGE_VERIFY", settings.image_verify), ("REVIEW", settings.review),
        ("AUDIT_QUERY", settings.audit_query),
    ):
        _validate_policy(name, policy)
    if settings.max_keys <= 0:
        raise InsecureRateLimitConfigError("RATE_LIMIT_MAX_KEYS must be a positive integer.")
    if settings.client_multiplier < 1:
        raise InsecureRateLimitConfigError("RATE_LIMIT_CLIENT_MULTIPLIER must be >= 1.")
    if settings.cleanup_interval_seconds <= 0:
        raise InsecureRateLimitConfigError("RATE_LIMIT_CLEANUP_INTERVAL_SECONDS must be a positive integer.")
