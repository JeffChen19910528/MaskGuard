"""Phase 10.6 §73/§74/§75/§76/§77/§137/§168: MANDATORY Redis leakage
tests — after real login + real analyze/review of synthetic sensitive
fixtures, directly dump EVERY Redis key/value in the test namespace and
confirm no raw sensitive values, tokens, or secrets are present. Reuses
the same synthetic-value list as Phase 10.4's audit leakage suite.
"""
from __future__ import annotations

import json

import pytest
import redis as redis_lib

from ..authorization.conftest import _write_role_mapping_file
from .conftest import _build_node, login_as

pytestmark = pytest.mark.usefixtures("ocr_env")

#: Same list as tests/api/audit/test_audit_leakage.py — kept in sync
#: deliberately (both suites protect the SAME underlying invariant:
#: MaskGuard never persists raw sensitive content anywhere outside the
#: request that produced it, Redis included).
_SYNTHETIC_SENSITIVE_VALUES = [
    "A123456789", "PA1234567", "1234567890123",
    "4111 1111 1111 1111", "4111111111111111",
    "demo_test_key_123456789", "demo_test_pw_123456",
]


def _dump_all_redis_values(client: redis_lib.Redis, namespace: str) -> str:
    blob = []
    for key in client.scan_iter(f"{namespace}*"):
        key_type = client.type(key)
        if key_type == "string":
            blob.append(client.get(key) or "")
        elif key_type == "hash":
            blob.append(json.dumps(client.hgetall(key)))
        blob.append(key)
    return "\n".join(blob)


def test_no_raw_sensitive_values_in_redis(monkeypatch, provider, redis_url, tmp_path):
    # A dedicated node with a HIGHER analyze capacity than the shared
    # `two_nodes` fixture's (which is intentionally small, for the
    # cross-instance rate-limit tests) — this test needs to process
    # every synthetic-sensitive-value fixture without hitting 429.
    import uuid

    role_mapping_path = _write_role_mapping_file(tmp_path)
    namespace = f"maskguard:test-leak-{uuid.uuid4().hex[:8]}:"
    token_options: dict = {}
    node = _build_node(
        monkeypatch, provider, redis_url, namespace, role_mapping_path, token_options,
        {"RATE_LIMIT_IMAGE_ANALYZE_CAPACITY": "20", "RATE_LIMIT_IMAGE_ANALYZE_WINDOW_SECONDS": "60"},
    )
    try:
        login_as(node, token_options, "reviewer-1")
        for filename in (
            "TaiwanID_clean.png", "Passport_clean.png", "BankAccount_clean.png",
            "CreditCard_clean.png", "APIKey_clean.png", "Password_clean.png",
        ):
            data = _dataset_image(filename)
            r = node.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
            assert r.status_code == 200, r.text

        client = redis_lib.Redis.from_url(_redis_url_of(node), decode_responses=True)
        dump = _dump_all_redis_values(client, namespace)
        for value in _SYNTHETIC_SENSITIVE_VALUES:
            assert value not in dump, f"synthetic sensitive value leaked into Redis: {value!r}"
    finally:
        node.__exit__(None, None, None)


def _dataset_image(filename: str) -> bytes:
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent.parent.parent / "benchmarks" / "results" / "dataset" / filename
    if not path.exists():
        pytest.skip(f"missing benchmark fixture {filename}")
    return path.read_bytes()


def test_no_session_cookie_value_reversible_from_redis_key_names(two_nodes):
    """§10: the session cookie VALUE is the Redis key's opaque id — this
    just confirms no ADDITIONAL copy of the raw cookie is stored inside
    the value payload beyond what's structurally required (the
    session_id field mirrors the key, which is expected and fine — the
    thing that must NOT appear is anything else sensitive)."""
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "operator-1")
    client = redis_lib.Redis.from_url(_redis_url_of(node_a), decode_responses=True)
    namespace = _namespace_of(node_a)
    for key in client.scan_iter(f"{namespace}session:*"):
        value = json.loads(client.get(key))
        assert set(value.keys()) == {"session_id", "identity", "created_at", "last_seen_at", "absolute_expires_at"}
        assert set(value["identity"].keys()) == {"subject", "issuer", "authenticated_at", "provider", "email", "display_name"}


def test_no_oidc_client_secret_in_redis(two_nodes):
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "operator-1")
    client = redis_lib.Redis.from_url(_redis_url_of(node_a), decode_responses=True)
    namespace = _namespace_of(node_a)
    dump = _dump_all_redis_values(client, namespace)
    assert "test-client-secret" not in dump


def _redis_url_of(node) -> str:
    from urllib.parse import quote

    kwargs = node.auth_runtime.session_store._client.connection_pool.connection_kwargs
    password = kwargs.get("password")
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{kwargs['host']}:{kwargs['port']}/{kwargs.get('db', 0)}"


def _namespace_of(node) -> str:
    return node.auth_runtime.session_store._prefix.rsplit("session:", 1)[0]
