"""Policy Engine (Skill.md §12, §18, §41): the only component allowed to decide
the final redaction action. AI/keyword layers only advise via risk score —
they never set the action directly (except explicit user rules, §20)."""
from __future__ import annotations

from ..config import MaskingConfig
from ..models import Detection, RedactionAction, RiskLevel

# High-risk categories that must never be silently skipped when uncertain (§18).
_ALWAYS_FAIL_SAFE_TYPES = {
    "SecretKeyValue", "JWT", "BearerToken", "OpaqueSecret",
    "CreditCard", "TaiwanID", "Passport", "BankAccount",
}

_RISK_ACTION_DEFAULT = {
    RiskLevel.CRITICAL: RedactionAction.FULL_MASK,
    RiskLevel.HIGH: RedactionAction.BLUR,
    RiskLevel.MEDIUM: RedactionAction.PARTIAL_MASK,
    RiskLevel.LOW: RedactionAction.NONE,
}

_ACTION_ALIASES = {
    "mask": RedactionAction.FULL_MASK,
    "full_mask": RedactionAction.FULL_MASK,
    "blur": RedactionAction.BLUR,
    "pixelate": RedactionAction.PIXELATE,
    "partial_mask": RedactionAction.PARTIAL_MASK,
}


class PolicyEngine:
    def __init__(self, masking: MaskingConfig, strict_mode: bool = False) -> None:
        self.masking = masking
        self.strict_mode = strict_mode

    def decide(self, detections: list[Detection]) -> list[Detection]:
        for detection in detections:
            if detection.action != RedactionAction.NONE and "user_rule" in detection.source_layers:
                continue  # explicit user-defined action (§20) is final

            if detection.unknown and (
                detection.type in _ALWAYS_FAIL_SAFE_TYPES or detection.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            ):
                # Fail-safe: uncertain classification on high-risk data must not be released unmasked (§18).
                detection.needs_review = True
                detection.action = RedactionAction.FULL_MASK
                continue

            if detection.risk_level == RiskLevel.CRITICAL:
                detection.action = _ACTION_ALIASES.get(
                    self.masking.critical_action.lower(), RedactionAction.FULL_MASK
                )
            else:
                detection.action = _RISK_ACTION_DEFAULT[detection.risk_level]

            if self.strict_mode and detection.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                # Strict Mode (§40): critical data always gets a full mask, no partial/blur leniency.
                if detection.risk_level == RiskLevel.CRITICAL:
                    detection.action = RedactionAction.FULL_MASK

        return [d for d in detections if d.action != RedactionAction.NONE]
