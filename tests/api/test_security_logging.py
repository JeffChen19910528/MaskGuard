"""§15/§28: raw sensitive text must NEVER appear in an API response OR in
captured application logs — for every major sensitive type, not just one.
Real Tesseract, real Core; nothing here fakes a result."""
from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.usefixtures("ocr_env")

# (fixture filename, raw sensitive value baked into that fixture by
# benchmarks/ocr/dataset.py — see _MAJOR_SENSITIVE_LINES) — all synthetic
# test data, never real personal/financial information.
_LEAK_CASES = [
    ("APIKey_clean.png", "demo_test_key_123456789"),
    ("Password_clean.png", "demo_test_pw_123456"),
    ("TaiwanID_clean.png", "A123456789"),
    ("CreditCard_clean.png", "4111 1111 1111 1111"),
    ("BankAccount_clean.png", "1234567890123"),
]


@pytest.mark.parametrize("filename,raw_value", _LEAK_CASES)
def test_raw_sensitive_value_never_appears_in_analyze_response(client, dataset_image, filename, raw_value):
    data = dataset_image(filename)
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert raw_value not in r.text
    # Also check a credit-card-shaped variant with separators stripped, in
    # case a future field serializes it differently.
    assert raw_value.replace(" ", "") not in r.text


@pytest.mark.parametrize("filename,raw_value", _LEAK_CASES)
def test_raw_sensitive_value_never_appears_in_application_logs(client, dataset_image, filename, raw_value, caplog):
    caplog.set_level(logging.DEBUG)
    data = dataset_image(filename)
    client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})

    log_text = caplog.text
    assert raw_value not in log_text
    assert raw_value.replace(" ", "") not in log_text


def test_redact_response_and_logs_never_contain_raw_values(client, dataset_image, caplog):
    caplog.set_level(logging.DEBUG)
    data = dataset_image("multiple_sensitive_values.png")
    r = client.post("/api/v1/redact", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200
    # The response IS an image (binary) — sensitive text obviously isn't a
    # UTF-8 substring of PNG pixel data, but the log line for this request
    # is text and must still be checked.
    for raw_value in ("A123456789", "4111 1111 1111 1111", "demo_test_key_123456789"):
        assert raw_value not in caplog.text


def test_access_log_only_contains_whitelisted_fields(client, dataset_image, caplog):
    """§15: request id, duration, file size, detection count, status are
    fine to log — filenames, OCR text, and detection raw values are not."""
    caplog.set_level(logging.INFO)
    data = dataset_image("Email_clean.png")
    client.post(
        "/api/v1/analyze",
        files={"file": ("definitely-not-a-safe-filename-demo@example.com.png", data, "image/png")},
    )
    # The uploaded filename is never used as a path (§14) and must never be
    # logged either — logging code only ever reads `len(data)`, never `file.filename`.
    assert "demo@example.com" not in caplog.text
    assert "definitely-not-a-safe-filename" not in caplog.text


def test_verify_response_and_logs_never_contain_raw_values(client, dataset_image, caplog):
    caplog.set_level(logging.DEBUG)
    data = dataset_image("APIKey_clean.png")
    r = client.post("/api/v1/verify", files={"file": ("upload.png", data, "image/png")})
    assert "demo_test_key_123456789" not in r.text
    assert "demo_test_key_123456789" not in caplog.text
