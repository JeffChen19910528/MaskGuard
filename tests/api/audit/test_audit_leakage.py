"""Phase 10.4 §111/§112/§113: MANDATORY leakage tests. Any confirmed raw
sensitive-value/token/secret occurrence in durable audit storage is FAIL
for the whole phase (§129).
"""
from __future__ import annotations

import json
import sqlite3

from .conftest import login_as

#: Synthetic-only values (§99) — the exact ground-truth strings the
#: existing benchmark dataset (`benchmarks/ocr/run.py::_GROUND_TRUTH_VALUES`)
#: already uses for its own test fixtures. Never real PII.
SYNTHETIC_SENSITIVE_VALUES = [
    "A123456789",  # TaiwanID
    "PA1234567",  # Passport
    "1234567890123",  # BankAccount
    "4111 1111 1111 1111",  # CreditCard
    "4111111111111111",
    "demo_test_key_123456789",  # APIKey
    "demo_test_pw_123456",  # Password
]

TOKEN_LOOKING_SUBSTRINGS = [
    "eyJ",  # a JWT's base64url header always starts with this
]


def _dump_raw_db_text(db_path: str) -> str:
    """Reads EVERY column of every row as raw text — not just through the
    typed API response, so this test would also catch a leak that only a
    direct DB read (not the query API's own serialization) would reveal."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT * FROM audit_events").fetchall()
    conn.close()
    return json.dumps(rows, default=str)


def test_no_raw_sensitive_values_in_audit_storage(client, ocr_env, dataset_image):
    login_as(client, "reviewer-1")

    for fixture, category in [
        ("TaiwanID_clean.png", "TaiwanID"), ("Passport_clean.png", "Passport"),
        ("BankAccount_clean.png", "BankAccount"), ("CreditCard_clean.png", "CreditCard"),
        ("APIKey_clean.png", "APIKey"), ("Password_clean.png", "Password"),
    ]:
        data = dataset_image(fixture)
        analyze_resp = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
        if analyze_resp.status_code != 200:
            continue  # a fixture that doesn't exist is skipped by dataset_image() itself
        body = analyze_resp.json()
        if body["detections"]:
            review_payload = {
                "review_token": body["review_token"],
                "items": [{"detection_id": body["detections"][0]["detection_id"], "review_status": "ACCEPTED"}],
            }
            client.post(
                "/api/v1/review",
                files={"file": ("upload.png", data, "image/png")},
                data={"review": json.dumps(review_payload)},
            )

    raw_dump = _dump_raw_db_text(client.audit_db_path)
    for value in SYNTHETIC_SENSITIVE_VALUES:
        assert value not in raw_dump, f"LEAK: synthetic sensitive value {value!r} found in audit storage"


def test_no_tokens_in_audit_storage(client, ocr_env, dataset_image):
    """§112: generate real session cookies, review tokens, etc. through
    genuine use, then confirm none of them appear anywhere in audit
    storage."""
    login_as(client, "reviewer-1")
    session_id = client.cookies.get("mg_sess")
    assert session_id  # sanity: we actually have a real, non-trivial session id to search for

    data = dataset_image("TaiwanID_clean.png")
    analyze_resp = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    review_token = analyze_resp.json()["review_token"]
    assert len(review_token) > 20  # sanity: a real token, not a placeholder

    raw_dump = _dump_raw_db_text(client.audit_db_path)
    assert session_id not in raw_dump, "LEAK: session id found in audit storage"
    assert review_token not in raw_dump, "LEAK: review token found in audit storage"
    for substr in TOKEN_LOOKING_SUBSTRINGS:
        assert substr not in raw_dump, f"LEAK: token-shaped substring {substr!r} found in audit storage"


def test_no_secret_in_audit_storage_or_response(client, ocr_env, dataset_image):
    """§113: the configured OIDC client secret must never appear in audit
    storage or any API response."""
    secret = "test-client-secret"  # matches conftest.py's OIDC_CLIENT_SECRET
    login_as(client, "reviewer-1")
    data = dataset_image("TaiwanID_clean.png")
    resp = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})

    raw_dump = _dump_raw_db_text(client.audit_db_path)
    assert secret not in raw_dump, "LEAK: OIDC client secret found in audit storage"
    assert secret not in resp.text, "LEAK: OIDC client secret found in an API response"


def test_no_sensitive_data_via_audit_query_api(client, ocr_env, dataset_image):
    """Same leakage class, but through the `/api/v1/audit` HTTP response
    specifically (not just a raw DB read) — proves the query API's own
    serialization doesn't reintroduce anything."""
    login_as(client, "reviewer-1")
    data = dataset_image("Passport_clean.png")
    client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})

    login_as(client, "auditor-1")
    resp = client.get("/api/v1/audit", params={"limit": 100})
    for value in SYNTHETIC_SENSITIVE_VALUES:
        assert value not in resp.text, f"LEAK: {value!r} found in /api/v1/audit response"
