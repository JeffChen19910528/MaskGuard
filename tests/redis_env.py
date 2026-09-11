"""Phase 10.6: a REAL, ephemeral `redis:7-alpine` Docker container for
tests — same "real infra, not mocked" convention as `ocr_env`
(benchmarks/ocr/env_check.py) and the mock-OIDC-with-real-crypto pattern
(Phase 10.2). Skips (never fails) when Docker isn't available, matching
`ocr_env`'s own skip-if-not-ready behavior.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid

import pytest


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def redis_container():
    """Session-scoped: ONE real Redis container for the whole test run —
    individual tests isolate via `REDIS_NAMESPACE` (a random prefix per
    test), never by starting a new container each time (§106/§160: test
    isolation via namespace, not via infrastructure churn).

    `TEST_REDIS_URL`, when set, is used DIRECTLY instead of spinning up a
    new container via `docker run` — for running the test suite FROM
    INSIDE a container that already sits on the same Docker network as a
    running Redis (e.g. the multi-instance compose profile's own `redis`
    service), where a nested `docker run` would need the host's Docker
    socket mounted in.
    """
    preset_url = os.environ.get("TEST_REDIS_URL")
    if preset_url:
        yield preset_url
        return

    if shutil.which("docker") is None:
        pytest.skip("Docker not available — cannot start a real Redis test instance")

    port = _free_port()
    name = f"maskguard-test-redis-{uuid.uuid4().hex[:8]}"
    try:
        subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name, "-p", f"{port}:6379", "redis:7-alpine"],
            check=True, capture_output=True, timeout=30, text=True,
        )
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"could not start a Redis test container: {exc}")

    url = f"redis://127.0.0.1:{port}/0"
    import redis as redis_lib

    client = redis_lib.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
    deadline = time.time() + 20
    ready = False
    while time.time() < deadline:
        try:
            if client.ping():
                ready = True
                break
        except Exception:
            time.sleep(0.2)
    if not ready:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        pytest.skip("Redis test container did not become ready in time")

    try:
        yield url
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture()
def redis_url(redis_container):
    """Function-scoped convenience — same container, exposed per-test."""
    return redis_container


@pytest.fixture()
def redis_namespace():
    """§105/§106: a fresh, random namespace per test — real key isolation
    within the ONE shared test container, never cross-test pollution."""
    return f"maskguard:test-{uuid.uuid4().hex[:12]}:"
