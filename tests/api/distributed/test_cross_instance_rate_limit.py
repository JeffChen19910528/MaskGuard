"""Phase 10.6 §38/§39/§64/§142/§148: MANDATORY cross-instance rate-limit
tests via real HTTP against two "node" TestClient apps. No Tesseract
needed — capacity is exhausted using anonymous requests that are denied
AFTER rate limiting runs (401), exactly like Phase 10.5's own bypass
tests (rate limiting always runs before authorization).

See conftest.py's module docstring for the one disclosed simplification:
both "node" apps in this single test PROCESS share the process-`lru_cache`d
Redis rate-limiter Python object — genuine cross-PROCESS independence is
proven separately (tests/test_redis_rate_limiter.py) and via live Docker.
This file still proves the full ROUTE -> DEPENDENCY -> REAL REDIS path is
wired correctly for a shared, alternating-node request pattern.
"""
from __future__ import annotations

from .conftest import login_as

_TINY_FILE = {"file": ("x.png", b"not-a-real-image", "image/png")}


def test_shared_limit_alternating_nodes_mandatory(two_nodes):
    """§38: MANDATORY — limit=3; A(nodeA), B(nodeB), C(nodeA), D(nodeB)
    -> 3 allowed, 1 rejected (shared, never 3-per-node)."""
    node_a, node_b, _ = two_nodes
    sequence = [node_a, node_b, node_a, node_b]
    statuses = [n.post("/api/v1/analyze", files=_TINY_FILE).status_code for n in sequence]
    assert statuses[:3] == [401, 401, 401]  # rate limit allowed, auth denied — 3 total
    assert statuses[3] == 429  # 4th, on the OTHER node, still rejected


def test_identity_scoped_limit_shared_across_nodes(two_nodes):
    """§40/§64: an AUTHENTICATED identity's limit is shared too, not
    reset by switching nodes."""
    node_a, node_b, token_options = two_nodes
    login_as(node_a, token_options, "operator-1")
    session_cookie = node_a.cookies.get("mg_sess")
    node_b.cookies.set("mg_sess", session_cookie)

    statuses = []
    for node in (node_a, node_b, node_a):
        statuses.append(node.post("/api/v1/analyze", files=_TINY_FILE).status_code)
    assert statuses == [415, 415, 415]  # authorized+rate-limit-allowed, rejected only for bad file content (3 of 3 capacity)
    fourth = node_b.post("/api/v1/analyze", files=_TINY_FILE).status_code
    assert fourth == 429


def test_node_switch_does_not_bypass_rate_limit(two_nodes):
    """§97/§146: an attacker alternating nodes specifically to try to
    evade rate limiting gets no benefit."""
    node_a, node_b, _ = two_nodes
    hit_429 = False
    for i in range(10):
        node = node_a if i % 2 == 0 else node_b
        status = node.post("/api/v1/analyze", files=_TINY_FILE).status_code
        if status == 429:
            hit_429 = True
            break
    assert hit_429, "expected a 429 within 10 alternating-node requests against capacity=3"
