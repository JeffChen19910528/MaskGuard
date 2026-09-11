"""Phase 10.7 §3/§4/§5/§6/§32: the production configuration validation
layer the phase brief asked to create "if one does not already exist" —
it did not (Phase 9-10.6 each validated their OWN config in isolation;
nothing validated the COMBINATION of security controls a deployment
actually needs).

Three profiles (§3):

- ``development`` (default): every Phase 10.x control remains fully
  opt-in, exactly as it has been since Phase 10.2 — setting
  ``MASKGUARD_ENV=production`` alone does NOT imply an enterprise
  identity/audit/rate-limit/distributed-state requirement (a bare
  production deployment with no enterprise-identity need, e.g. an
  internal tool behind its own network perimeter, remains valid and
  supported — this is a deliberate, disclosed design choice continuing
  every prior phase's opt-in precedent, not an oversight).
- ``single-instance-enterprise``: OIDC + Authorization + Audit + Rate
  Limiting are ALL REQUIRED (hard startup failure otherwise). Redis is
  NOT required (single instance has no cross-node consistency need).
- ``multi-instance-enterprise``: everything ``single-instance-enterprise``
  requires, PLUS Redis.

Selected via ``MASKGUARD_DEPLOYMENT_PROFILE`` (default
``development`` — §0's opt-in pattern, continued). This is intentionally
a NEW, EXPLICIT opt-in rather than inferring "enterprise" from
``MASKGUARD_ENV=production`` — inferring it would silently change
production's meaning for every deployment that adopted
``MASKGUARD_ENV=production`` since Phase 9, before any enterprise
control existed at all.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

DEVELOPMENT = "development"
SINGLE_INSTANCE_ENTERPRISE = "single-instance-enterprise"
MULTI_INSTANCE_ENTERPRISE = "multi-instance-enterprise"

_VALID_PROFILES = frozenset({DEVELOPMENT, SINGLE_INSTANCE_ENTERPRISE, MULTI_INSTANCE_ENTERPRISE})


class InvalidDeploymentProfileError(RuntimeError):
    """§32/§68: malformed/contradictory production configuration MUST
    fail startup — never a silent downgrade to development-grade
    security."""


@dataclass(frozen=True)
class DeploymentProfile:
    name: str

    @property
    def requires_oidc(self) -> bool:
        return self.name in (SINGLE_INSTANCE_ENTERPRISE, MULTI_INSTANCE_ENTERPRISE)

    @property
    def requires_audit(self) -> bool:
        return self.name in (SINGLE_INSTANCE_ENTERPRISE, MULTI_INSTANCE_ENTERPRISE)

    @property
    def requires_rate_limit(self) -> bool:
        return self.name in (SINGLE_INSTANCE_ENTERPRISE, MULTI_INSTANCE_ENTERPRISE)

    @property
    def requires_redis(self) -> bool:
        return self.name == MULTI_INSTANCE_ENTERPRISE


@lru_cache
def get_deployment_profile() -> DeploymentProfile:
    raw = (os.environ.get("MASKGUARD_DEPLOYMENT_PROFILE") or DEVELOPMENT).strip().lower()
    if raw not in _VALID_PROFILES:
        raise InvalidDeploymentProfileError(
            f"MASKGUARD_DEPLOYMENT_PROFILE={raw!r} is not one of {sorted(_VALID_PROFILES)}."
        )
    return DeploymentProfile(name=raw)


def validate_deployment_profile(
    profile: DeploymentProfile, *, oidc_enabled: bool, authz_configured: bool,
    audit_enabled: bool, rate_limit_enabled: bool, redis_enabled: bool,
) -> None:
    """§4/§5/§6/§32: the actual enforcement. Called unconditionally at
    startup (app.py) — a malformed/contradictory combination for the
    DECLARED profile is a hard failure, never a warning, never a silent
    fallback to weaker behavior (§68's explicit instruction)."""
    if profile.name == DEVELOPMENT:
        return  # §0: no requirement — every control remains independently opt-in

    missing = []
    if profile.requires_oidc and not oidc_enabled:
        missing.append("OIDC_ENABLED=true")
    if profile.requires_oidc and oidc_enabled and not authz_configured:
        # §5: OIDC_ENABLED=true with no role mapping means every
        # authenticated identity has ZERO permissions (Phase 10.3's own
        # default-deny design) — technically "secure" (fails closed) but
        # almost certainly not what an operator declaring an enterprise
        # profile intended. Flagged as a hard requirement here so the
        # contradiction surfaces at startup, not as silent 403s later.
        missing.append("AUTHZ_ROLE_MAPPING_FILE (OIDC is enabled but no role mapping is configured)")
    if profile.requires_audit and not audit_enabled:
        missing.append("AUDIT_ENABLED=true")
    if profile.requires_rate_limit and not rate_limit_enabled:
        missing.append("RATE_LIMIT_ENABLED=true")
    if profile.requires_redis and not redis_enabled:
        missing.append("REDIS_ENABLED=true")

    if missing:
        raise InvalidDeploymentProfileError(
            f"MASKGUARD_DEPLOYMENT_PROFILE={profile.name!r} requires: {', '.join(missing)}. "
            "Refusing to start with a partially-configured enterprise profile — see "
            "docs/enterprise-architecture.md 'Production Profiles' for the exact requirements "
            "of each profile."
        )
