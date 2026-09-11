"""X-Request-ID correlation (§16)."""
from __future__ import annotations

import re

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_server_generates_a_request_id_when_client_omits_one(client):
    r = client.get("/api/v1/health")
    request_id = r.headers.get("x-request-id")
    assert request_id
    assert _UUID_RE.match(request_id)


def test_server_echoes_a_safe_client_supplied_request_id(client):
    r = client.get("/api/v1/health", headers={"X-Request-ID": "client-supplied-id-42"})
    assert r.headers.get("x-request-id") == "client-supplied-id-42"


def test_unsafe_client_request_id_is_replaced_not_echoed(client):
    unsafe = "id with spaces and <script>"
    r = client.get("/api/v1/health", headers={"X-Request-ID": unsafe})
    returned = r.headers.get("x-request-id")
    assert returned != unsafe
    assert _UUID_RE.match(returned)


def test_error_responses_also_carry_a_request_id(client):
    r = client.post("/api/v1/analyze", files={"file": ("upload.txt", b"nope", "text/plain")})
    assert r.headers.get("x-request-id")
    assert r.json()["error"]["request_id"] == r.headers["x-request-id"]


def test_request_id_is_never_derived_from_the_filename(client):
    r = client.post(
        "/api/v1/analyze",
        files={"file": ("super-secret-patient-name.png", b"not an image", "image/png")},
    )
    request_id = r.headers.get("x-request-id")
    assert "super-secret-patient-name" not in request_id
