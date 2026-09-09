"""Centralized Intrinsic Critical Sensitive Type policy (Skill.md §5/§12).

Some sensitive-data TYPES are critical by their nature, independent of how
confident OCR happened to be about the surrounding pixels: a correctly
format-validated Taiwan ID, a Luhn-valid credit card, a passport/bank-account
value that matched an explicit label, or a matched credential-shaped secret
is already conclusive evidence of what it is. The plain `risk_score = base *
confidence` formula in `risk_engine.py` can let a merely slightly-noisy OCR
pass drag one of these below the CRITICAL threshold — confirmed: TaiwanID at
a realistic confidence of 0.85 scores 0.765 -> HIGH -> BLUR instead of
FULL_MASK, even though the value was unambiguously identified as a Taiwan ID.
That is an information-recoverable downgrade for data Skill.md explicitly
requires FULL_MASK for.

This module is the SINGLE place that names which types qualify and what
counts as sufficient DETECTION EVIDENCE — no detector hard-codes this, and
Policy Engine is not aware of this at all. Only `RiskEngine` consults it, and
only to apply a risk_score FLOOR:

  Detection Type + Detection Evidence -> intrinsic floor -> RiskEngine
                                                                 |
                                                                 v
                                                    (existing, unchanged)
                                                    RiskLevel -> PolicyEngine
                                                                 -> Action

It never overrides a genuinely higher score, and never applies when evidence
is insufficient or the detection is itself flagged `unknown` — an AI-only
guess must never be promoted to Critical just because it happens to carry a
critical-sounding type string. Policy Engine's CRITICAL -> FULL_MASK mapping
(already existing, unchanged) does the rest; this module has no concept of
"action" at all.
"""
from __future__ import annotations

from ..models import Detection

# Types that are intrinsically Critical (Skill.md §5 Authentication/Security
# data, §12 Critical examples) WHEN sufficient detection evidence backs them.
INTRINSIC_CRITICAL_TYPES = frozenset(
    {
        "TaiwanID",
        "Passport",
        "BankAccount",
        "CreditCard",
        "SecretKeyValue",  # covers Password / API Key / Secret Key / Private Key (§5, matched via key=value pattern)
        "BearerToken",  # Access Token
        "JWT",
    }
)

# Must be >= the CRITICAL threshold used by RiskLevel.from_score() (0.80).
_CRITICAL_FLOOR = 0.85

# Detection source layers that are themselves independently corroborating:
#   - "regex": the value matched a format-enforcing pattern (for CreditCard
#     this already implies a passed Luhn check; regex_detector.py never
#     emits a CreditCard Detection that failed it).
#   - "context": the value matched an explicit label (Skill.md's own
#     "a label makes an otherwise-ambiguous value classifiable" mechanism,
#     §10 Layer 3) — a labeled "護照：<value>" pair is not ambiguous evidence.
#   - "user_rule": an operator-authored rule (§20) that already carries its
#     own explicit risk/action and is left untouched elsewhere in RiskEngine.
_SUFFICIENT_EVIDENCE_LAYERS = frozenset({"regex", "context", "user_rule"})


def has_sufficient_evidence(detection: Detection) -> bool:
    """Whether THIS detection's evidence is strong enough to trust its type
    label even when raw OCR confidence alone would suggest otherwise.

    Deliberately NOT based on `detection.type` alone — an AI-only guess
    (always `unknown=True`) must never qualify, no matter what type string
    it happens to carry (requirement: don't let a type NAME alone, or vague/
    ambiguous evidence, force a Critical classification).
    """
    if detection.unknown:
        return False
    return any(layer in _SUFFICIENT_EVIDENCE_LAYERS for layer in detection.source_layers)


def intrinsic_floor_for(detection: Detection) -> float | None:
    """Risk-score floor to apply, or None if this detection's type isn't
    intrinsically critical, or its evidence isn't sufficient to trust it."""
    if detection.type not in INTRINSIC_CRITICAL_TYPES:
        return None
    if not has_sufficient_evidence(detection):
        return None
    return _CRITICAL_FLOOR
