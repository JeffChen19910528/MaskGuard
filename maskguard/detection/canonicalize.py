"""Detection type canonicalization (Phase 6.3).

Root cause this addresses (OCR benchmark, Phase 6.2 baseline — 5 confirmed
false positives, none of them an OCR failure or a CandidateValueDetector
issue): `RegexDetector`'s Taiwan-mobile-number pattern reports type
"PhoneTW", while `ContextDetector`'s generic "電話/phone/tel" label match
reports type "Phone" for the exact same underlying value. Because
`RiskEngine._merge_overlapping` (risk/risk_engine.py) only merges detections
that share both an overlapping bounding box AND the same `.type`, that
type-name split defeats the merge and the same phone number survives as two
separate `Detection` objects downstream — a duplicate/mismatched-type
finding (benchmark FP), not a real second sensitive value.

"Phone" is the canonical type: `RegexDetector`'s "09xx-xxx-xxx" pattern is a
Taiwan-specific detector SUBTYPE of the general phone-number concept, not a
distinct sensitive-data category — `RiskEngine._BASE_SCORE` and
`PolicyEngine` already score/act on "Phone" and "PhoneTW" identically (same
0.55 base score, no PhoneTW-specific branch anywhere in policy), so
canonicalizing changes zero risk/policy outcomes, only type identity.

This module is the single place that type identity gets normalized, applied
uniformly to a detector-output list regardless of which detector(s) produced
a hit or the order they ran in — never by having one detector suppress
another's finding (that would be an order-dependent hack that breaks the
moment detector order changes, a new detector is added, or Local AI/PaddleOCR
joins the mix). Individual detectors keep reporting their own most-specific
type (e.g. `RegexDetector` still emits "PhoneTW" as evidence of exactly which
pattern matched) — `canonicalize_types` is applied once, after every
detector's output has been collected, and preserves the original type on
`Detection.source_type` for evidence/reporting.
"""
from __future__ import annotations

from ..models import Detection

#: original detector-reported type -> canonical type. Only entries here are
#: rewritten; every other type passes through untouched.
CANONICAL_TYPE_ALIASES: dict[str, str] = {
    "PhoneTW": "Phone",
}


def canonicalize_types(detections: list[Detection]) -> list[Detection]:
    """Rewrite each detection's `.type` to its canonical form in place.

    The original detector-reported type is preserved on `.source_type`
    (left as `None` when no aliasing applied). Does not merge, drop, or
    reorder anything — duplicate merging is left entirely to whatever
    same-type overlap logic already runs downstream (e.g.
    `RiskEngine._merge_overlapping`), so this function has no opinion about
    detector order and cannot suppress a genuine second finding.
    """
    for detection in detections:
        canonical = CANONICAL_TYPE_ALIASES.get(detection.type)
        if canonical is None:
            continue
        detection.source_type = detection.source_type or detection.type
        detection.type = canonical
    return detections
