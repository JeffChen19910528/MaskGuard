"""Phase 10.4 §70-72/§86: audit event sanitization/validation. Pure unit
tests — no Tesseract, no HTTP, no Docker.
"""
from __future__ import annotations

import pytest

from maskguard.api.audit.config import AuditSettings
from maskguard.api.audit.event_types import IMAGE_ANALYZE
from maskguard.api.audit.models import RESULT_SUCCESS
from maskguard.api.audit.sanitizer import AuditValidationError, build_event


@pytest.fixture()
def settings() -> AuditSettings:
    return AuditSettings(audit_enabled=True)


def test_valid_event_builds(settings):
    event = build_event(
        settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id="iss|sub", issuer="iss",
        request_id="req-1", operation="image.analyze", resource_type="image", resource_id="p-1",
        result=RESULT_SUCCESS, metadata={"detection_count": 2},
    )
    assert event.event_type == IMAGE_ANALYZE
    assert event.metadata == {"detection_count": 2}
    assert event.hash is None  # stamped only by storage.py


def test_unknown_event_type_rejected(settings):
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type="NOT_A_REAL_EVENT", actor_type="user", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
        )


def test_unknown_actor_type_rejected(settings):
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="superuser", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
        )


def test_unknown_result_rejected(settings):
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result="MAYBE",
        )


@pytest.mark.parametrize(
    "bad_key",
    ["access_token", "refresh_token", "client_secret", "session_cookie", "api_key", "review_token",
     "authorization", "bearer_token", "pkce_verifier", "nonce", "password", "db_password"],
)
def test_forbidden_metadata_key_rejected(settings, bad_key):
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
            metadata={bad_key: "whatever"},
        )


def test_metadata_value_must_be_primitive(settings):
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
            metadata={"nested": {"a": 1}},
        )


def test_metadata_bytes_rejected(settings):
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
            metadata={"blob": b"raw bytes"},
        )


def test_metadata_too_many_keys_rejected():
    settings = AuditSettings(audit_enabled=True, max_metadata_keys=2)
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
            metadata={"a": 1, "b": 2, "c": 3},
        )


def test_actor_id_length_limit_enforced():
    settings = AuditSettings(audit_enabled=True)
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id="x" * 10_000, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
        )


def test_whole_event_size_limit_enforced():
    settings = AuditSettings(audit_enabled=True, max_event_bytes=100, max_metadata_value_length=1000, max_metadata_keys=20)
    with pytest.raises(AuditValidationError):
        build_event(
            settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
            request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
            metadata={f"key{i}": "y" * 50 for i in range(20)},
        )


def test_control_characters_stripped_from_strings(settings):
    event = build_event(
        settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
        request_id="req\n1\x00malicious", operation="x", resource_type=None, resource_id=None,
        result=RESULT_SUCCESS,
    )
    assert "\n" not in event.request_id
    assert "\x00" not in event.request_id


def test_log_injection_newline_stripped_from_metadata_value(settings):
    event = build_event(
        settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
        request_id=None, operation="x", resource_type=None, resource_id=None, result=RESULT_SUCCESS,
        metadata={"note": "line1\nFAKE_LOG_LINE event=AUTHORIZATION_ALLOWED"},
    )
    assert "\n" not in event.metadata["note"]


def test_sql_fragment_in_field_is_treated_as_plain_text_not_executed(settings):
    """§50/§86: parameterized queries mean a SQL-looking string is just a
    string — this test documents that expectation at the sanitizer layer
    (storage.py's own parameterization is verified in test_audit_storage.py)."""
    event = build_event(
        settings, event_type=IMAGE_ANALYZE, actor_type="user", actor_id=None, issuer=None,
        request_id=None, operation="x", resource_type=None,
        resource_id="'; DROP TABLE audit_events; --", result=RESULT_SUCCESS,
    )
    assert event.resource_id == "'; DROP TABLE audit_events; --"  # stored verbatim as DATA, never as SQL
