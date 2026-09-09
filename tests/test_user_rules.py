from maskguard.detection.user_rules import UserRule, UserRuleDetector
from maskguard.models import RedactionAction, RiskLevel

from conftest import line


def test_user_pattern_rule_matches_and_uses_explicit_action():
    rule = UserRule(name="InternalEmployeeID", pattern=r"EMP-\d{6}", action=RedactionAction.FULL_MASK, risk=RiskLevel.HIGH)
    tokens = line("Employee:", "EMP-123456")
    detections = UserRuleDetector([rule]).detect(tokens)
    assert len(detections) == 1
    assert detections[0].action == RedactionAction.FULL_MASK
    assert detections[0].risk_level == RiskLevel.HIGH


def test_user_keyword_rule_matches():
    rule = UserRule(name="InternalServer", keywords=["Production"], action=RedactionAction.BLUR, risk=RiskLevel.MEDIUM)
    tokens = line("DB", "Server:", "Production")
    detections = UserRuleDetector([rule]).detect(tokens)
    assert any(d.type == "UserRule:InternalServer" for d in detections)
