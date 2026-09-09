"""P0 regression tests: Intrinsic Critical Sensitive Data Risk Classification.

Confirms that TaiwanID/Passport/BankAccount/CreditCard and credential/token
types are classified CRITICAL -> FULL_MASK whenever detection evidence is
sufficient, even under lower OCR confidence — and that this is NOT a blanket
type-name rule: insufficient/ambiguous evidence must not force Critical.
"""
from maskguard.config import MaskingConfig
from maskguard.models import BoundingBox, Detection, RedactionAction, RiskLevel
from maskguard.policy.policy_engine import PolicyEngine
from maskguard.risk.intrinsic_critical import has_sufficient_evidence, intrinsic_floor_for
from maskguard.risk.risk_engine import RiskEngine

_BOX = BoundingBox(x=0, y=0, width=100, height=20)


def _detection(type_, confidence, source_layers, unknown=False) -> Detection:
    return Detection(
        type=type_,
        text="dummy",
        confidence=confidence,
        bounding_box=_BOX,
        source_layers=list(source_layers),
        unknown=unknown,
    )


def _score_and_decide(detection: Detection) -> Detection:
    scored = RiskEngine().score([detection], [])
    decided = PolicyEngine(MaskingConfig()).decide(scored)
    assert len(decided) == 1
    return decided[0]


# ---------------------------------------------------------------------------
# 1-6: valid, well-evidenced detections of each intrinsically-critical type
# must land CRITICAL -> FULL_MASK, regardless of realistic confidence dips.
# ---------------------------------------------------------------------------


def test_taiwan_id_valid_regex_detection_is_critical_full_mask():
    detection = _detection("TaiwanID", confidence=0.85, source_layers=["regex"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.action == RedactionAction.FULL_MASK


def test_passport_valid_context_detection_is_critical_full_mask():
    detection = _detection("Passport", confidence=0.75, source_layers=["context"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.action == RedactionAction.FULL_MASK


def test_bank_account_valid_context_detection_is_critical_full_mask():
    detection = _detection("BankAccount", confidence=0.75, source_layers=["context"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.action == RedactionAction.FULL_MASK


def test_credit_card_valid_luhn_detection_is_critical_full_mask():
    detection = _detection("CreditCard", confidence=0.93, source_layers=["regex"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.action == RedactionAction.FULL_MASK


def test_api_key_valid_regex_detection_is_critical_full_mask():
    detection = _detection("SecretKeyValue", confidence=0.9, source_layers=["regex"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.action == RedactionAction.FULL_MASK


def test_password_valid_regex_detection_is_critical_full_mask():
    # Password values are matched by the same SecretKeyValue regex pattern
    # ("password" is one of its keyword alternatives) — same type, same path.
    detection = _detection("SecretKeyValue", confidence=0.9, source_layers=["regex"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.action == RedactionAction.FULL_MASK


# ---------------------------------------------------------------------------
# 7: a critical type with LOWER OCR confidence must not be downgraded to
# HIGH/BLUR, as long as evidence (regex/context match) is still sufficient.
# This is the exact bug being fixed: TaiwanID at confidence 0.85 previously
# scored 0.9*0.85=0.765 -> HIGH -> BLUR.
# ---------------------------------------------------------------------------


def test_critical_type_with_lower_confidence_is_not_downgraded_when_evidence_sufficient():
    low_confidence_taiwan_id = _detection("TaiwanID", confidence=0.60, source_layers=["regex"])
    result = _score_and_decide(low_confidence_taiwan_id)
    assert result.risk_level == RiskLevel.CRITICAL, (
        "regex-validated TaiwanID must stay CRITICAL even at low OCR confidence"
    )
    assert result.action == RedactionAction.FULL_MASK


def test_bank_account_with_lower_confidence_is_not_downgraded():
    detection = _detection("BankAccount", confidence=0.5, source_layers=["context"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.CRITICAL
    assert result.action == RedactionAction.FULL_MASK


# ---------------------------------------------------------------------------
# 8: invalid/ambiguous evidence must NOT be promoted to Critical just
# because the type string happens to match — the floor is evidence-gated,
# not type-name-gated.
# ---------------------------------------------------------------------------


def test_ai_only_guess_with_critical_type_name_is_not_force_promoted():
    # unknown=True (AI-only, no corroborating regex/context match) must never
    # qualify for the intrinsic floor, regardless of type string.
    ambiguous = _detection("TaiwanID", confidence=0.4, source_layers=["ai"], unknown=True)
    assert intrinsic_floor_for(ambiguous) is None
    assert has_sufficient_evidence(ambiguous) is False

    result = _score_and_decide(ambiguous)
    # Existing §18 fail-safe (unrelated to this fix) still applies to
    # unknown=True detections of these types — see policy_engine.py's
    # _ALWAYS_FAIL_SAFE_TYPES — so this still ends up FULL_MASK, but via the
    # pre-existing uncertainty path, NOT via the new intrinsic-critical floor.
    assert result.needs_review is True


def test_non_intrinsic_type_never_gets_a_floor_regardless_of_evidence():
    # A type that isn't in INTRINSIC_CRITICAL_TYPES at all (e.g. a plain
    # regex-matched URL) must never be floored, no matter the evidence layer.
    detection = _detection("URL", confidence=0.9, source_layers=["regex"])
    assert intrinsic_floor_for(detection) is None


# ---------------------------------------------------------------------------
# 9: non-critical data (Email/Phone/Name/Address) must keep existing
# behavior — no floor, same score formula as before this change.
# ---------------------------------------------------------------------------


def test_email_keeps_existing_medium_risk_behavior():
    detection = _detection("Email", confidence=0.95, source_layers=["regex"])
    result = _score_and_decide(detection)
    assert intrinsic_floor_for(detection) is None
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.action == RedactionAction.PARTIAL_MASK


def test_phone_keeps_existing_medium_risk_behavior():
    detection = _detection("PhoneTW", confidence=0.85, source_layers=["regex"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.action == RedactionAction.PARTIAL_MASK


def test_personal_name_keeps_existing_medium_risk_behavior():
    detection = _detection("PersonalName", confidence=0.75, source_layers=["context"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.action == RedactionAction.PARTIAL_MASK


def test_address_keeps_existing_medium_risk_behavior():
    detection = _detection("Address", confidence=0.75, source_layers=["context"])
    result = _score_and_decide(detection)
    assert result.risk_level == RiskLevel.MEDIUM
    assert result.action == RedactionAction.PARTIAL_MASK


# ---------------------------------------------------------------------------
# 10: Policy Engine remains the only component that sets the final action.
# ---------------------------------------------------------------------------


def test_risk_engine_never_sets_action_even_with_intrinsic_floor_applied():
    detection = _detection("TaiwanID", confidence=0.6, source_layers=["regex"])
    scored = RiskEngine().score([detection], [])
    assert scored[0].action == RedactionAction.NONE
    assert scored[0].risk_level == RiskLevel.CRITICAL  # floor applied to risk, not action


def test_policy_engine_is_sole_action_decider_for_intrinsic_critical_types():
    detection = _detection("BankAccount", confidence=0.5, source_layers=["context"])
    scored = RiskEngine().score([detection], [])
    assert scored[0].action == RedactionAction.NONE  # still unset after Risk Engine
    decided = PolicyEngine(MaskingConfig()).decide(scored)
    assert decided[0].action == RedactionAction.FULL_MASK  # only set once Policy Engine runs
