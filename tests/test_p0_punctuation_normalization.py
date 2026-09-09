"""Phase 6.1 P0-1 regression tests: the "‥" (U+2025 TWO DOT LEADER) OCR
colon-variant found by the Phase 6 benchmark (Address_clean false negative)
must normalize the same way the already-covered colon variants do — without
letting it leak into being treated as arbitrary data content anywhere else.
"""
from maskguard.detection.context_detector import ContextDetector
from maskguard.detection.line_matching import build_line_index
from maskguard.detection.normalization import normalize_for_context
from maskguard.detection.regex_detector import RegexDetector
from maskguard.detection.user_rules import UserRule, UserRuleDetector
from maskguard.models import RedactionAction, RiskLevel

from conftest import line


# ---------------------------------------------------------------------------
# 1 & 2: normal fullwidth colon vs. the "‥" OCR variant must behave the same.
# ---------------------------------------------------------------------------


def test_normal_fullwidth_colon_address_label_is_recognized():
    tokens = line("地址", "：", "台北市信義區")
    detections = ContextDetector().detect(tokens)
    assert any(d.type == "Address" and d.text == "台北市信義區" for d in detections)


def test_two_dot_leader_ocr_variant_address_label_is_recognized():
    tokens = line("地址", "‥", "台北市信義區")
    detections = ContextDetector().detect(tokens)
    assert any(d.type == "Address" and d.text == "台北市信義區" for d in detections)


def test_two_dot_leader_normalizes_identically_to_fullwidth_colon():
    normal = normalize_for_context(build_line_index(line("地址", "：", "台北市信義區")))
    variant = normalize_for_context(build_line_index(line("地址", "‥", "台北市信義區")))
    assert normal.normalized_text == variant.normalized_text == "地址:台北市信義區"


# ---------------------------------------------------------------------------
# 3: ContextDetector correctly identifies the label under the OCR variant
# (repeated from above with a per-character-tokenized label, mirroring the
# exact real-OCR shape confirmed in Phase 6).
# ---------------------------------------------------------------------------


def test_context_detector_handles_per_character_label_with_two_dot_leader():
    tokens = line("地", "址", "‥", "台", "北", "市", "信", "義", "區")
    detections = ContextDetector().detect(tokens)
    address = next((d for d in detections if d.type == "Address"), None)
    assert address is not None
    assert address.text == "台北市信義區"


# ---------------------------------------------------------------------------
# 4: RegexDetector / UserRuleDetector must not produce a wrong bounding box
# because of the new mapping — the label tokens must stay excluded from the
# matched value's box.
# ---------------------------------------------------------------------------


def test_regex_detector_bbox_unaffected_by_two_dot_leader_label():
    tokens = line("信用卡", "‥", "4111", "1111", "1111", "1111")
    detections = RegexDetector().detect(tokens)
    credit_card = next(d for d in detections if d.type == "CreditCard")

    value_tokens = tokens[2:]
    label_right_edge = tokens[1].bounding_box.x + tokens[1].bounding_box.width
    assert credit_card.bounding_box.x >= label_right_edge
    assert credit_card.bounding_box.x == min(t.bounding_box.x for t in value_tokens)


def test_user_rule_bbox_unaffected_by_two_dot_leader_label():
    rule = UserRule(name="EmpIDPattern", pattern=r"EMP-\d{6}", action=RedactionAction.FULL_MASK, risk=RiskLevel.HIGH)
    tokens = line("員", "工", "編", "號", "‥", "EMP-123456")
    detections = UserRuleDetector([rule]).detect(tokens)
    match = next(d for d in detections if d.type == "UserRule:EmpIDPattern")

    value_token = tokens[5]
    assert match.text == "EMP-123456"
    assert match.bounding_box.x == value_token.bounding_box.x
    assert match.bounding_box.width == value_token.bounding_box.width


# ---------------------------------------------------------------------------
# 5: must not affect Email / API Key / other sensitive types — "‥" only
# acts as context punctuation normalization, never as arbitrary data
# content, and never corrupts an unrelated value elsewhere on the same line.
# ---------------------------------------------------------------------------


def test_email_detection_unaffected_by_two_dot_leader_elsewhere_on_line():
    tokens = line("備註", "‥", "admin@example.com")
    detections = RegexDetector().detect(tokens)
    email = next(d for d in detections if d.type == "Email")
    assert email.text == "admin@example.com"  # value itself untouched


def test_two_dot_leader_normalization_never_misclassifies_an_unrelated_value():
    # "‥" -> ":" is a character-level substitution (the same rule every
    # other punctuation-variant entry already uses, e.g. full-width "："),
    # so it CAN appear inside what OCR returned as a single token, not just
    # at a token boundary. That is fine: substituting one punctuation glyph
    # for its canonical form never turns arbitrary text into a recognized
    # sensitive-data SHAPE by itself — this string still isn't a
    # "keyword=value"/"keyword:value" pair, so it must not become
    # SecretKeyValue just because "‥" now reads as ":".
    tokens = line("demo‥test‥key‥123456789")
    normalized = normalize_for_context(build_line_index(tokens))
    assert normalized.normalized_text == "demo:test:key:123456789"

    detections = RegexDetector().detect(tokens)
    assert not any(d.type == "SecretKeyValue" for d in detections)


def test_api_key_value_itself_is_not_corrupted_by_two_dot_leader_normalization():
    tokens = line("API_KEY", "‥", "demo_test_key_123456789")
    detections = RegexDetector().detect(tokens)
    secret = next(d for d in detections if d.type == "SecretKeyValue")
    assert secret.text == "demo_test_key_123456789"
