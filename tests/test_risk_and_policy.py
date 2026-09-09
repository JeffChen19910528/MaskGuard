from maskguard.config import MaskingConfig
from maskguard.models import BoundingBox, Detection, KeywordHit, RiskLevel, RedactionAction
from maskguard.policy.policy_engine import PolicyEngine
from maskguard.risk.risk_engine import RiskEngine


def _det(type_, confidence, x=0, y=0, unknown=False) -> Detection:
    return Detection(
        type=type_,
        text="dummy",
        confidence=confidence,
        bounding_box=BoundingBox(x=x, y=y, width=50, height=20),
        unknown=unknown,
    )


def test_critical_type_scores_high_and_gets_full_mask():
    detections = RiskEngine().score([_det("TaiwanID", 0.9)], [])
    assert detections[0].risk_level == RiskLevel.CRITICAL

    decided = PolicyEngine(MaskingConfig()).decide(detections)
    assert decided[0].action == RedactionAction.FULL_MASK


def test_keyword_boost_raises_risk_level():
    box = BoundingBox(x=0, y=0, width=50, height=20)
    detection = _det("Unknown", 0.5, x=60, y=0)
    hit = KeywordHit(keyword="password", category="Credential", critical=True, bounding_box=box)
    scored = RiskEngine().score([detection], [hit])
    assert scored[0].risk_score > 0.15  # base(0.3)*0.5 + boost(0.2)


def test_overlapping_same_type_detections_merge():
    a = _det("Email", 0.6, x=10, y=10)
    b = _det("Email", 0.9, x=12, y=10)  # overlapping box, higher confidence
    merged = RiskEngine().score([a, b], [])
    assert len(merged) == 1
    assert merged[0].confidence == 0.9


def test_unknown_high_risk_detection_fails_safe_to_full_mask():
    detection = _det("OpaqueSecret", 0.5, unknown=True)
    detection.risk_score = 0.7
    detection.risk_level = RiskLevel.HIGH
    decided = PolicyEngine(MaskingConfig()).decide([detection])
    assert decided[0].action == RedactionAction.FULL_MASK
    assert decided[0].needs_review is True


def test_low_risk_detection_is_dropped_from_final_list():
    detection = _det("URL", 0.6)
    detection.risk_score = 0.15
    detection.risk_level = RiskLevel.LOW
    decided = PolicyEngine(MaskingConfig()).decide([detection])
    assert decided == []
