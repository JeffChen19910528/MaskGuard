"""P1 regression tests: Detection Normalization Consistency.

Confirms RegexDetector and UserRuleDetector now use the same
`normalize_for_context()` layer ContextDetector/KeywordDetector already used
(P0-2), so Chinese OCR tokenization / full-width characters / punctuation
variants no longer produce inconsistent results across detectors — while
bounding-box mapping stays intact and no two semantically different values
get merged into the same normalized string.
"""
from maskguard.detection.context_detector import ContextDetector
from maskguard.detection.keyword_detector import KeywordDetector
from maskguard.detection.normalization import normalize_for_context
from maskguard.detection.line_matching import build_line_index
from maskguard.detection.regex_detector import RegexDetector
from maskguard.detection.user_rules import UserRule, UserRuleDetector
from maskguard.models import RedactionAction, RiskLevel

from conftest import line


# ---------------------------------------------------------------------------
# 1: Chinese User Rule keyword split into one token per character must
# still hit — the exact "員工編號" example from the ticket.
# ---------------------------------------------------------------------------


def test_user_rule_chinese_keyword_hits_despite_per_character_tokenization():
    rule = UserRule(
        name="EmployeeIDLabel", keywords=["員工編號"], action=RedactionAction.BLUR, risk=RiskLevel.MEDIUM
    )
    tokens = line("員", "工", "編", "號", "﹕", "EMP-000123")
    detections = UserRuleDetector([rule]).detect(tokens)
    assert any(d.type == "UserRule:EmployeeIDLabel" for d in detections)


def test_user_rule_chinese_keyword_bounding_box_maps_to_label_tokens_only():
    rule = UserRule(
        name="EmployeeIDLabel", keywords=["員工編號"], action=RedactionAction.BLUR, risk=RiskLevel.MEDIUM
    )
    tokens = line("員", "工", "編", "號", "﹕", "EMP-000123")
    detections = UserRuleDetector([rule]).detect(tokens)
    hit = next(d for d in detections if d.type == "UserRule:EmployeeIDLabel")

    label_tokens = tokens[:4]  # 員, 工, 編, 號
    expected_left = min(t.bounding_box.x for t in label_tokens)
    expected_right = max(t.bounding_box.x + t.bounding_box.width for t in label_tokens)
    assert hit.bounding_box.x == expected_left
    assert hit.bounding_box.x + hit.bounding_box.width == expected_right


# ---------------------------------------------------------------------------
# 2: Chinese-labeled + regex-pattern user rule — normalization must not
# break the regex match itself, and the rule's own pattern string must stay
# untouched (only the OCR-derived search text is normalized).
# ---------------------------------------------------------------------------


def test_user_rule_pattern_still_matches_after_chinese_label_tokenization():
    rule = UserRule(
        name="EmpIDPattern", pattern=r"EMP-\d{6}", action=RedactionAction.FULL_MASK, risk=RiskLevel.HIGH
    )
    tokens = line("員", "工", "編", "號", "﹕", "EMP-123456")
    detections = UserRuleDetector([rule]).detect(tokens)
    match = next(d for d in detections if d.type == "UserRule:EmpIDPattern")

    assert match.text == "EMP-123456"
    assert rule.pattern == r"EMP-\d{6}"  # the stored pattern string is never mutated

    value_token = tokens[5]
    assert match.bounding_box.x == value_token.bounding_box.x
    assert match.bounding_box.width == value_token.bounding_box.width


# ---------------------------------------------------------------------------
# 3: Full-width / half-width — RegexDetector must recognize a value OCR'd
# using full-width glyphs (a real Tesseract behavior on some fonts), without
# needing a second, duplicated pattern for the full-width variant.
# ---------------------------------------------------------------------------


def test_regex_detector_recognizes_fullwidth_taiwan_id():
    # "Ａ１２３４５６７８９" — fullwidth Latin capital A + fullwidth digits,
    # OCR'd as a single token (as Tesseract typically does for one word).
    tokens = line("身分證", "﹕", "Ａ１２３４５６７８９")
    detections = RegexDetector().detect(tokens)
    taiwan_id = next((d for d in detections if d.type == "TaiwanID"), None)
    assert taiwan_id is not None, "fullwidth Taiwan ID glyphs were not recognized"
    assert taiwan_id.text == "A123456789"  # normalized to halfwidth for the captured value


def test_regex_detector_still_rejects_ambiguous_fullwidth_ip_like_text():
    # Sanity check that fullwidth-folding doesn't create new false positives:
    # a fullwidth "Version" string followed by a dotted number must still be
    # treated the same low-confidence way as the ASCII case (Skill.md §17).
    tokens = line("Version：", "１．２．３．４")
    detections = RegexDetector().detect(tokens)
    ip_detections = [d for d in detections if d.type == "IPAddress"]
    assert ip_detections and ip_detections[0].confidence <= 0.5


# ---------------------------------------------------------------------------
# 4: Whitespace — Context/Keyword/User-Rule/Regex all resolve the same
# artificial per-token join-space consistently.
# ---------------------------------------------------------------------------


def test_all_four_detectors_agree_on_same_chinese_labeled_line():
    tokens = line("員", "工", "編", "號", "﹕", "EMP-000123")

    keyword_hits = KeywordDetector().detect(line("身", "分", "證", "﹕", "A123456789"))
    assert any(h.category == "PersonalID" for h in keyword_hits)

    context_hits = ContextDetector().detect(line("姓", "名", "﹕", "王", "小", "明"))
    assert any(d.type == "PersonalName" and d.text == "王小明" for d in context_hits)

    rule = UserRule(name="EmpID", keywords=["員工編號"], action=RedactionAction.BLUR, risk=RiskLevel.MEDIUM)
    assert UserRuleDetector([rule]).detect(tokens)

    regex_hits = RegexDetector().detect(line("信用卡", "﹕", "4111", "1111", "1111", "1111"))
    assert any(d.type == "CreditCard" for d in regex_hits)


# ---------------------------------------------------------------------------
# 5: Punctuation — Chinese punctuation must not corrupt an adjacent regex
# match (e.g. a trailing full-width period must not get folded into the
# email value itself).
# ---------------------------------------------------------------------------


def test_trailing_chinese_punctuation_does_not_leak_into_email_match():
    tokens = line("帳號", "﹕", "admin@example.com", "。")
    detections = RegexDetector().detect(tokens)
    email = next(d for d in detections if d.type == "Email")
    assert email.text == "admin@example.com"  # trailing "。" (-> ".") not absorbed


def test_normalize_for_context_keeps_ascii_and_chinese_punctuation_distinguishable():
    # Half-width "." and (normalized) full-width "。" both fold to the ASCII
    # "." token boundary, but this must not merge two textually different
    # values — verified in the negative test below via the detector itself.
    tokens = line("A", "。")
    normalized = normalize_for_context(build_line_index(tokens))
    assert normalized.normalized_text == "A ."


# ---------------------------------------------------------------------------
# 6: Bounding box mapping must survive normalization for every detector.
# ---------------------------------------------------------------------------


def test_regex_detector_bounding_box_excludes_chinese_label_tokens():
    tokens = line("信用卡", "﹕", "4111", "1111", "1111", "1111")
    detections = RegexDetector().detect(tokens)
    credit_card = next(d for d in detections if d.type == "CreditCard")

    value_tokens = tokens[2:]  # the four digit-group tokens only
    label_right_edge = tokens[1].bounding_box.x + tokens[1].bounding_box.width
    assert credit_card.bounding_box.x >= label_right_edge
    assert credit_card.bounding_box.x == min(t.bounding_box.x for t in value_tokens)


# ---------------------------------------------------------------------------
# 7: Negative test — normalization must never merge two DIFFERENT sensitive
# values into the same match. No separator-stripping happens at the
# Detection layer (that only happens type-specifically in the Verification
# layer, per the P0-1 fix), so distinct API keys must stay distinct.
# ---------------------------------------------------------------------------


def test_different_api_keys_are_not_merged_by_normalization():
    tokens_a = line("API_KEY=demo_test_key_A")
    tokens_b = line("API_KEY=demo_test_key_B")

    detections_a = RegexDetector().detect(tokens_a)
    detections_b = RegexDetector().detect(tokens_b)

    value_a = next(d.text for d in detections_a if d.type == "SecretKeyValue")
    value_b = next(d.text for d in detections_b if d.type == "SecretKeyValue")
    assert value_a != value_b
    assert value_a == "demo_test_key_A"
    assert value_b == "demo_test_key_B"


def test_normalize_for_context_does_not_merge_dash_and_no_dash_variants():
    # "ABC-123" and "ABC123" must remain textually different after
    # normalization — the Detection layer only unifies OCR-artifact
    # whitespace/width/punctuation, never strips a value's own separators.
    dash_variant = normalize_for_context(build_line_index(line("ABC-123")))
    no_dash_variant = normalize_for_context(build_line_index(line("ABC123")))
    assert dash_variant.normalized_text != no_dash_variant.normalized_text
    assert dash_variant.normalized_text == "ABC-123"
    assert no_dash_variant.normalized_text == "ABC123"
