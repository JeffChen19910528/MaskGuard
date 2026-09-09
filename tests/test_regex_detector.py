from maskguard.detection.regex_detector import RegexDetector

from conftest import line


def test_detects_email():
    tokens = line("Email:", "john.doe@example.com")
    detections = RegexDetector().detect(tokens)
    assert any(d.type == "Email" and d.text == "john.doe@example.com" for d in detections)


def test_detects_credit_card_across_tokens_via_luhn():
    tokens = line("4111", "1111", "1111", "1111")  # valid Luhn test number
    detections = RegexDetector().detect(tokens)
    cards = [d for d in detections if d.type == "CreditCard"]
    assert len(cards) == 1
    assert cards[0].confidence > 0.9


def test_rejects_invalid_credit_card_number():
    tokens = line("1234", "5678", "9012", "3459")  # fails Luhn
    detections = RegexDetector().detect(tokens)
    assert not any(d.type == "CreditCard" for d in detections)


def test_version_string_is_not_flagged_as_high_confidence_ip():
    tokens = line("Version:", "1.2.3.4")
    detections = RegexDetector().detect(tokens)
    ip_detections = [d for d in detections if d.type == "IPAddress"]
    assert ip_detections and ip_detections[0].confidence <= 0.5


def test_detects_taiwan_id():
    tokens = line("身分證:", "A123456789")
    detections = RegexDetector().detect(tokens)
    assert any(d.type == "TaiwanID" for d in detections)


def test_detects_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    tokens = line(jwt)
    detections = RegexDetector().detect(tokens)
    assert any(d.type == "JWT" for d in detections)


def test_detects_secret_key_value_pair():
    tokens = line("API_KEY=sk_live_abcdef123456")
    detections = RegexDetector().detect(tokens)
    assert any(d.type == "SecretKeyValue" and "sk_live" in d.text for d in detections)
