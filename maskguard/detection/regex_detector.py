"""Layer 1 — Regex detection for fixed-format sensitive data (Skill.md §10 Layer 1).

Matches against `normalize_for_context()`'s output (same as Context/Keyword
detection), but for a narrower reason than those two: none of the patterns
below ever match CJK text, so the CJK-token-boundary-space-dropping half of
that normalizer is a no-op here. What DOES matter for this detector is the
OTHER half — full-width -> half-width character folding and OCR punctuation-
variant unification (e.g. "．" -> ".") — which fixes values Tesseract OCR'd
using full-width digit/letter glyphs (visually "4111" but reads as the
full-width code points "４１１１"). This is a lossless, purely cosmetic-OCR-
artifact fix: it never strips or merges separators that change a value's
actual meaning (e.g. "ABC-123" and "ABC123" are NOT folded together — no
_Pattern below treats "-" as insignificant, each pattern's own regex decides
that on a per-type basis, e.g. PhoneTW's `[- ]?`)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Detection, OcrToken
from ..textline import group_into_lines
from .line_matching import build_line_index, merge_bounding_boxes
from .normalization import normalize_for_context


@dataclass(frozen=True)
class _Pattern:
    type: str
    regex: re.Pattern
    base_confidence: float
    group: int = 0  # which regex group holds the sensitive value


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_PATTERNS: list[_Pattern] = [
    _Pattern("Email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), 0.95),
    _Pattern("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), 0.97),
    _Pattern("BearerToken", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.]{10,}\b"), 0.9),
    _Pattern(
        "SecretKeyValue",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
            r"secret[_-]?key|client[_-]?secret|password|passwd|pwd)\s*[=:]\s*"
            r"([^\s]{4,})"
        ),
        0.9,
        group=1,
    ),
    _Pattern("URL", re.compile(r"https?://[^\s]+"), 0.6),
    _Pattern("TaiwanID", re.compile(r"\b[A-Z][12]\d{8}\b"), 0.85),
    _Pattern("PhoneTW", re.compile(r"\b09\d{2}[- ]?\d{3}[- ]?\d{3}\b"), 0.85),
    _Pattern("IPAddress", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"), 0.4),
    _Pattern("CreditCard", re.compile(r"\b(?:\d[ -]?){13,19}\b"), 0.5),
]


class RegexDetector:
    """Matches against whole OCR lines so multi-token values (e.g. spaced
    credit card digits) are still caught, then maps back to bounding boxes.
    """

    def detect(self, tokens: list[OcrToken]) -> list[Detection]:
        detections: list[Detection] = []
        for line in group_into_lines(tokens):
            index = build_line_index(line)
            normalized = normalize_for_context(index)
            for pattern in _PATTERNS:
                for match in pattern.regex.finditer(normalized.normalized_text):
                    value = match.group(pattern.group)
                    span_start, span_end = match.span(pattern.group)
                    confidence = pattern.base_confidence

                    if pattern.type == "CreditCard":
                        digits = re.sub(r"[ -]", "", value)
                        if not (13 <= len(digits) <= 19) or not digits.isdigit():
                            continue
                        if not _luhn_valid(digits):
                            continue
                        confidence = 0.93

                    matched_tokens = normalized.tokens_for_normalized_span(span_start, span_end)
                    if not matched_tokens:
                        continue
                    box = merge_bounding_boxes([t.bounding_box for t in matched_tokens])
                    detections.append(
                        Detection(
                            type=pattern.type,
                            text=value,
                            confidence=confidence,
                            bounding_box=box,
                            source_layers=["regex"],
                        )
                    )
        return detections
