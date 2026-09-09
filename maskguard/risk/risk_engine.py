"""Risk Engine (Skill.md §11): assigns each detection a 0.00-1.00 risk score,
mapped to LOW/MEDIUM/HIGH/CRITICAL. Combines the base severity of the data
*type* with its detection confidence and any nearby keyword boosts (§10 Layer 2).

After that base scoring, `intrinsic_critical.intrinsic_floor_for()` may raise
the score to a CRITICAL-band floor for a small set of intrinsically-critical
types (Taiwan ID, Passport, Bank Account, Credit Card, and credential/token
types) whose detection evidence is strong enough to trust regardless of raw
OCR confidence — see `risk/intrinsic_critical.py` for the full rationale.
This only ever raises the score, never lowers it, and only Risk Engine
applies it; Policy Engine's CRITICAL -> FULL_MASK mapping is unchanged."""
from __future__ import annotations

from ..models import Detection, KeywordHit, RedactionAction, RiskLevel
from .intrinsic_critical import intrinsic_floor_for

_BASE_SCORE: dict[str, float] = {
    # Authentication / security — always critical (§5, §12 Critical)
    "SecretKeyValue": 0.95,
    "JWT": 0.95,
    "BearerToken": 0.9,
    "OpaqueSecret": 0.75,
    # Financial / high-risk personal identifiers (§4, §3.1 High Risk)
    "CreditCard": 0.9,
    "TaiwanID": 0.9,
    "Passport": 0.88,
    "BankAccount": 0.85,
    # Medium-risk personal information (§3.1 Medium Risk, §12 High -> Blur)
    "PersonalName": 0.55,
    "Phone": 0.55,
    "PhoneTW": 0.55,
    "Address": 0.55,
    "Email": 0.55,
    "Birthday": 0.45,
    "EmployeeID": 0.45,
    "CustomerID": 0.45,
    "URL": 0.25,
    "IPAddress": 0.25,
    "Unknown": 0.3,
}

_KEYWORD_BOOST = {True: 0.2, False: 0.08}  # critical vs. non-critical keyword nearby


def _same_line(box_a, box_b) -> bool:
    top = max(box_a.y, box_b.y)
    bottom = min(box_a.y + box_a.height, box_b.y + box_b.height)
    return bottom > top


def _overlaps(box_a, box_b) -> bool:
    ax0, ay0, ax1, ay1 = box_a.as_rect()
    bx0, by0, bx1, by1 = box_b.as_rect()
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


class RiskEngine:
    def score(self, detections: list[Detection], keyword_hits: list[KeywordHit]) -> list[Detection]:
        merged = self._merge_overlapping(detections)
        for detection in merged:
            if detection.action != RedactionAction.NONE and "user_rule" in detection.source_layers:
                continue  # user rules already set an explicit risk/action (§20)

            base = _BASE_SCORE.get(detection.type, 0.3)
            score = base * max(detection.confidence, 0.3)

            for hit in keyword_hits:
                if _same_line(detection.bounding_box, hit.bounding_box):
                    score += _KEYWORD_BOOST[hit.critical]

            score = min(score, 1.0)
            floor = intrinsic_floor_for(detection)
            if floor is not None:
                score = max(score, floor)

            detection.risk_score = score
            detection.risk_level = RiskLevel.from_score(detection.risk_score)
        return merged

    def _merge_overlapping(self, detections: list[Detection]) -> list[Detection]:
        merged: list[Detection] = []
        for detection in detections:
            duplicate = next(
                (
                    m
                    for m in merged
                    if m.type == detection.type and _overlaps(m.bounding_box, detection.bounding_box)
                ),
                None,
            )
            if duplicate is None:
                merged.append(detection)
                continue
            if detection.confidence > duplicate.confidence:
                duplicate.confidence = detection.confidence
                duplicate.bounding_box = detection.bounding_box
                duplicate.text = detection.text
            duplicate.source_layers = list(dict.fromkeys(duplicate.source_layers + detection.source_layers))
            duplicate.unknown = duplicate.unknown and detection.unknown
        return merged
