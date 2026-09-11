"""Phase 10.6 §114/§178: Redis configuration validation. No Docker/Redis
required — pure config-object tests."""
from __future__ import annotations

import pytest

from maskguard.api.redisstate.config import InsecureRedisConfigError, RedisSettings, validate_redis_config


def _settings(**overrides) -> RedisSettings:
    base = dict(
        enabled=True, url="redis://redis:6379/0", password=None,
        socket_timeout_seconds=2.0, socket_connect_timeout_seconds=2.0,
        max_connections=50, retry_limit=1, namespace="maskguard:test:",
    )
    base.update(overrides)
    return RedisSettings(**base)


def test_disabled_config_always_passes():
    validate_redis_config("production", RedisSettings(enabled=False, url=None))


def test_valid_enabled_config_passes():
    validate_redis_config("production", _settings())
    validate_redis_config("development", _settings())


def test_missing_url_rejected_when_enabled():
    with pytest.raises(InsecureRedisConfigError):
        validate_redis_config("development", _settings(url=None))


def test_zero_timeout_rejected():
    with pytest.raises(InsecureRedisConfigError):
        validate_redis_config("development", _settings(socket_timeout_seconds=0))
    with pytest.raises(InsecureRedisConfigError):
        validate_redis_config("development", _settings(socket_connect_timeout_seconds=0))


def test_zero_max_connections_rejected():
    with pytest.raises(InsecureRedisConfigError):
        validate_redis_config("development", _settings(max_connections=0))


def test_negative_retry_limit_rejected():
    with pytest.raises(InsecureRedisConfigError):
        validate_redis_config("development", _settings(retry_limit=-1))


def test_excessive_retry_limit_rejected():
    with pytest.raises(InsecureRedisConfigError):
        validate_redis_config("development", _settings(retry_limit=6))


def test_zero_retry_limit_is_valid():
    # 0 = no retry (fail fast) is a legitimate, explicit choice — not the
    # ambiguous "0 = unlimited" pattern forbidden elsewhere.
    validate_redis_config("development", _settings(retry_limit=0))


def test_resolved_namespace_falls_back_to_environment():
    settings = RedisSettings(enabled=True, url="redis://x/0", namespace="")
    assert settings.resolved_namespace("production") == "maskguard:production:"


def test_connection_url_injects_password_without_logging():
    settings = _settings(url="redis://host:6379/0", password="s3cret")
    url = settings.connection_url()
    assert "s3cret" in url  # only place the password is ever assembled
    assert url.startswith("redis://:s3cret@")


def test_connection_url_does_not_duplicate_existing_credentials():
    settings = _settings(url="redis://:already@host:6379/0", password="ignored")
    assert settings.connection_url() == "redis://:already@host:6379/0"


def test_connection_url_raises_without_url():
    settings = RedisSettings(enabled=True, url=None)
    with pytest.raises(InsecureRedisConfigError):
        settings.connection_url()
