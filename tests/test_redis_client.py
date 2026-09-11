"""Phase 10.6 §50/§51/§52/§98: client.py against a real Redis container."""
from __future__ import annotations

import pytest
import redis as redis_lib

from maskguard.api.redisstate.client import RedisUnavailableError, get_redis_client, ping, safe_call
from maskguard.api.redisstate.config import RedisSettings


def _settings(redis_url, namespace) -> RedisSettings:
    return RedisSettings(
        enabled=True, url=redis_url, password=None,
        socket_timeout_seconds=1.0, socket_connect_timeout_seconds=1.0,
        max_connections=10, retry_limit=0, namespace=namespace,
    )


def test_get_client_and_ping(redis_url, redis_namespace):
    get_redis_client.cache_clear()
    settings = _settings(redis_url, redis_namespace)
    client = get_redis_client(settings)
    assert ping(client) is True


def test_ping_returns_false_never_raises_on_bad_target():
    bad_settings = RedisSettings(
        enabled=True, url="redis://127.0.0.1:1/0", socket_timeout_seconds=0.3,
        socket_connect_timeout_seconds=0.3, max_connections=5, retry_limit=0, namespace="x:",
    )
    get_redis_client.cache_clear()
    client = get_redis_client(bad_settings)
    assert ping(client) is False  # never raises


def test_safe_call_translates_redis_errors():
    def _boom():
        raise redis_lib.exceptions.ConnectionError("simulated")

    with pytest.raises(RedisUnavailableError) as exc_info:
        safe_call("test_op", _boom)
    # §98: generic message only — never the underlying connection detail.
    assert "simulated" not in str(exc_info.value)
    assert "test_op" in str(exc_info.value)


def test_safe_call_passes_through_successful_result(redis_url, redis_namespace):
    get_redis_client.cache_clear()
    client = get_redis_client(_settings(redis_url, redis_namespace))
    safe_call("set", client.set, f"{redis_namespace}k", "v")
    assert safe_call("get", client.get, f"{redis_namespace}k") == "v"


def test_connection_pool_is_bounded(redis_url, redis_namespace):
    get_redis_client.cache_clear()
    settings = _settings(redis_url, redis_namespace)
    client = get_redis_client(settings)
    assert client.connection_pool.max_connections == 10
