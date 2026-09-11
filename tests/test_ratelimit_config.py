"""Phase 10.5 §55/§59/§60/§61/§62/§113: rate-limit configuration
validation. No HTTP, no Tesseract."""
from __future__ import annotations

import pytest

from maskguard.api.ratelimit.config import (
    InsecureRateLimitConfigError,
    RateLimitPolicy,
    RateLimitSettings,
    validate_production_rate_limit_config,
)


def _settings(**overrides) -> RateLimitSettings:
    base = dict(
        enabled=True,
        auth=RateLimitPolicy(20, 60), read=RateLimitPolicy(60, 60),
        image_analyze=RateLimitPolicy(20, 60), image_redact=RateLimitPolicy(20, 60),
        image_verify=RateLimitPolicy(30, 60), review=RateLimitPolicy(30, 60),
        audit_query=RateLimitPolicy(30, 60),
        client_multiplier=5, max_keys=50_000, cleanup_interval_seconds=60,
        trust_proxy_headers=False,
    )
    base.update(overrides)
    return RateLimitSettings(**base)


def test_valid_config_passes_in_every_environment():
    validate_production_rate_limit_config("production", _settings())
    validate_production_rate_limit_config("development", _settings())


@pytest.mark.parametrize("field", ["auth", "read", "image_analyze", "image_redact", "image_verify", "review", "audit_query"])
def test_zero_capacity_rejected_not_treated_as_unlimited(field):
    policy = RateLimitPolicy(0, 60)
    with pytest.raises(InsecureRateLimitConfigError):
        validate_production_rate_limit_config("production", _settings(**{field: policy}))


def test_negative_capacity_rejected():
    with pytest.raises(InsecureRateLimitConfigError):
        validate_production_rate_limit_config("production", _settings(auth=RateLimitPolicy(-1, 60)))


def test_zero_window_rejected():
    with pytest.raises(InsecureRateLimitConfigError):
        validate_production_rate_limit_config("production", _settings(auth=RateLimitPolicy(10, 0)))


def test_zero_max_keys_rejected():
    with pytest.raises(InsecureRateLimitConfigError):
        validate_production_rate_limit_config("production", _settings(max_keys=0))


def test_client_multiplier_below_one_rejected():
    with pytest.raises(InsecureRateLimitConfigError):
        validate_production_rate_limit_config("production", _settings(client_multiplier=0))


def test_zero_cleanup_interval_rejected():
    with pytest.raises(InsecureRateLimitConfigError):
        validate_production_rate_limit_config("production", _settings(cleanup_interval_seconds=0))


def test_validation_runs_even_when_disabled():
    # §55: validated in EVERY environment/state, not only when enabled —
    # a malformed value must never lurk unnoticed until the operator
    # flips RATE_LIMIT_ENABLED=true later.
    with pytest.raises(InsecureRateLimitConfigError):
        validate_production_rate_limit_config("development", _settings(enabled=False, auth=RateLimitPolicy(0, 60)))


def test_policy_for_returns_correct_class():
    settings = _settings()
    assert settings.policy_for("AUTH") is settings.auth
    assert settings.policy_for("AUDIT_QUERY") is settings.audit_query


def test_production_scale_config_is_valid():
    # §113: realistic, non-trivial production-sized values also pass.
    prod = _settings(
        auth=RateLimitPolicy(30, 60), read=RateLimitPolicy(120, 60),
        image_analyze=RateLimitPolicy(60, 60), image_redact=RateLimitPolicy(60, 60),
        image_verify=RateLimitPolicy(90, 60), review=RateLimitPolicy(90, 60),
        audit_query=RateLimitPolicy(60, 60), max_keys=100_000, client_multiplier=5,
    )
    validate_production_rate_limit_config("production", prod)
