"""Phase 10.7 §3/§4/§5/§6/§32: deployment-profile validation. No HTTP,
no Redis."""
from __future__ import annotations

import pytest

from maskguard.api.deployment_profile import (
    DEVELOPMENT,
    MULTI_INSTANCE_ENTERPRISE,
    SINGLE_INSTANCE_ENTERPRISE,
    DeploymentProfile,
    InvalidDeploymentProfileError,
    get_deployment_profile,
    validate_deployment_profile,
)


def _full_enterprise_kwargs(**overrides):
    base = dict(oidc_enabled=True, authz_configured=True, audit_enabled=True, rate_limit_enabled=True, redis_enabled=True)
    base.update(overrides)
    return base


def test_development_profile_never_requires_anything():
    profile = DeploymentProfile(DEVELOPMENT)
    validate_deployment_profile(
        profile, oidc_enabled=False, authz_configured=False, audit_enabled=False,
        rate_limit_enabled=False, redis_enabled=False,
    )


def test_single_instance_enterprise_requires_oidc_authz_audit_rate_limit():
    profile = DeploymentProfile(SINGLE_INSTANCE_ENTERPRISE)
    validate_deployment_profile(profile, **_full_enterprise_kwargs(redis_enabled=False))  # Redis not required


@pytest.mark.parametrize("missing_field", ["oidc_enabled", "authz_configured", "audit_enabled", "rate_limit_enabled"])
def test_single_instance_enterprise_fails_closed_when_missing(missing_field):
    profile = DeploymentProfile(SINGLE_INSTANCE_ENTERPRISE)
    kwargs = _full_enterprise_kwargs(redis_enabled=False)
    kwargs[missing_field] = False
    with pytest.raises(InvalidDeploymentProfileError):
        validate_deployment_profile(profile, **kwargs)


def test_multi_instance_enterprise_requires_redis_too():
    profile = DeploymentProfile(MULTI_INSTANCE_ENTERPRISE)
    validate_deployment_profile(profile, **_full_enterprise_kwargs())
    with pytest.raises(InvalidDeploymentProfileError):
        validate_deployment_profile(profile, **_full_enterprise_kwargs(redis_enabled=False))


def test_oidc_without_role_mapping_rejected_for_enterprise_profile():
    # §5: OIDC on with no role mapping is technically fail-closed (zero
    # permissions) but almost certainly a misconfiguration for a
    # deployment declaring an enterprise profile.
    profile = DeploymentProfile(SINGLE_INSTANCE_ENTERPRISE)
    with pytest.raises(InvalidDeploymentProfileError):
        validate_deployment_profile(profile, **_full_enterprise_kwargs(redis_enabled=False, authz_configured=False))


def test_invalid_profile_name_rejected(monkeypatch):
    monkeypatch.setenv("MASKGUARD_DEPLOYMENT_PROFILE", "totally-bogus")
    get_deployment_profile.cache_clear()
    try:
        with pytest.raises(InvalidDeploymentProfileError):
            get_deployment_profile()
    finally:
        get_deployment_profile.cache_clear()


def test_default_profile_is_development(monkeypatch):
    monkeypatch.delenv("MASKGUARD_DEPLOYMENT_PROFILE", raising=False)
    get_deployment_profile.cache_clear()
    try:
        assert get_deployment_profile().name == DEVELOPMENT
    finally:
        get_deployment_profile.cache_clear()


def test_profile_requirement_properties():
    dev = DeploymentProfile(DEVELOPMENT)
    single = DeploymentProfile(SINGLE_INSTANCE_ENTERPRISE)
    multi = DeploymentProfile(MULTI_INSTANCE_ENTERPRISE)
    assert not dev.requires_oidc and not dev.requires_redis
    assert single.requires_oidc and single.requires_audit and single.requires_rate_limit and not single.requires_redis
    assert multi.requires_redis
