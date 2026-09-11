"""Phase 6.3 regression tests: Phone/PhoneTW canonical type consolidation.

Root cause (Phase 6.2 benchmark, 5 confirmed FPs): RegexDetector reports the
Taiwan-mobile pattern as type "PhoneTW", ContextDetector reports the same
underlying value (matched via a "電話/phone/tel" label) as type "Phone" —
two Detection objects for one real value, which also defeats
RiskEngine._merge_overlapping's same-type-and-overlap dedup.
"""
from maskguard.config import MaskingConfig
from maskguard.detection.canonicalize import canonicalize_types
from maskguard.detection.context_detector import ContextDetector
from maskguard.detection.regex_detector import RegexDetector
from maskguard.models import RedactionAction, RiskLevel
from maskguard.policy.policy_engine import PolicyEngine
from maskguard.risk.risk_engine import RiskEngine

from conftest import line


def test_regex_detector_still_reports_raw_phonetw():
    # Canonicalization is a separate, explicit step — the detector itself
    # keeps reporting its own most-specific type as evidence.
    tokens = line("電話：", "0912345678")
    detections = RegexDetector().detect(tokens)
    assert any(d.type == "PhoneTW" for d in detections)


def test_regex_phonetw_canonicalizes_to_phone():
    tokens = line("電話：", "0912345678")
    detections = RegexDetector().detect(tokens)
    canonicalize_types(detections)
    assert all(d.type != "PhoneTW" for d in detections)
    assert any(d.type == "Phone" and d.source_type == "PhoneTW" for d in detections)


def test_context_detector_taiwan_phone_canonicalizes_to_phone():
    tokens = line("電話：", "0912345678")
    detections = ContextDetector().detect(tokens)
    canonicalize_types(detections)
    assert any(d.type == "Phone" for d in detections)
    # ContextDetector already reported "Phone" natively, so no aliasing fired.
    phone = next(d for d in detections if d.type == "Phone")
    assert phone.source_type is None


def test_non_aliased_types_pass_through_untouched():
    tokens = line("Email:", "john@example.com")
    detections = RegexDetector().detect(tokens)
    canonicalize_types(detections)
    assert any(d.type == "Email" and d.source_type is None for d in detections)


def test_regex_and_context_same_phone_value_merge_into_one_finding():
    # Same line -> RegexDetector fires PhoneTW, ContextDetector fires Phone,
    # both on the identical value/overlapping bbox.
    tokens = line("電話：", "0912345678")
    detections = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    canonicalize_types(detections)

    merged = RiskEngine().score(detections, [])
    phone_findings = [d for d in merged if d.type == "Phone"]
    assert len(phone_findings) == 1, f"expected one merged Phone finding, got {phone_findings}"
    assert set(phone_findings[0].source_layers) == {"regex", "context"}


def test_two_different_phone_values_stay_separate_findings():
    # Two distinct Taiwan phone numbers on two separate lines — each caught
    # by both RegexDetector and ContextDetector, but the two VALUES must
    # never collapse into a single finding just because they share a type.
    line_a = line("電話：", "0912345678", y=0)
    line_b = line("電話：", "0987654321", y=40)
    tokens = line_a + line_b
    detections = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    canonicalize_types(detections)

    merged = RiskEngine().score(detections, [])
    phone_texts = {d.text for d in merged if d.type == "Phone"}
    assert phone_texts == {"0912345678", "0987654321"}, phone_texts


def _risk_and_action(detection_type: str) -> tuple[float, RiskLevel, RedactionAction]:
    tokens = line("電話：", "0912345678")
    if detection_type == "PhoneTW":
        detections = RegexDetector().detect(tokens)
        detections = [d for d in detections if d.type == "PhoneTW"]
    else:
        detections = ContextDetector().detect(tokens)
        detections = [d for d in detections if d.type == "Phone"]

    scored = RiskEngine().score(detections, [])
    decided = PolicyEngine(MaskingConfig()).decide(scored)
    d = decided[0]
    return d.risk_score, d.risk_level, d.action


def test_canonicalization_does_not_change_risk_score_or_policy_action():
    """Before (raw PhoneTW) vs. after (canonicalized Phone) must score and
    act identically — Phase 6.3 must not change Risk/Policy semantics."""
    before_score, before_level, before_action = _risk_and_action("PhoneTW")

    tokens = line("電話：", "0912345678")
    regex_detections = [d for d in RegexDetector().detect(tokens) if d.type == "PhoneTW"]
    canonicalize_types(regex_detections)
    scored = RiskEngine().score(regex_detections, [])
    decided = PolicyEngine(MaskingConfig()).decide(scored)
    after_score, after_level, after_action = decided[0].risk_score, decided[0].risk_level, decided[0].action

    assert before_level == after_level == RiskLevel.MEDIUM
    assert before_action == after_action == RedactionAction.PARTIAL_MASK
    assert before_score == after_score
