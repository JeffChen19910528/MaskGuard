"""User-defined detection rules (Skill.md §20): regex pattern or keyword list,
each with an explicit action/risk that bypasses the normal risk scoring.

Both `pattern` and `keywords` matching happen against `normalize_for_context()`'s
output — the same normalization Context/Keyword/Regex detection use — so a
user-authored Chinese keyword (e.g. "員工編號") still hits even when OCR
returns it as one token per character. The rule's own `pattern`/`keywords`
strings loaded from YAML are never rewritten; only the OCR-derived search
text is normalized before matching against them."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..models import Detection, OcrToken, RedactionAction, RiskLevel
from ..textline import group_into_lines
from .line_matching import build_line_index, merge_bounding_boxes
from .normalization import normalize_for_context

_RISK_SCORE = {
    RiskLevel.LOW: 0.15,
    RiskLevel.MEDIUM: 0.45,
    RiskLevel.HIGH: 0.7,
    RiskLevel.CRITICAL: 0.9,
}


@dataclass
class UserRule:
    name: str
    action: RedactionAction
    risk: RiskLevel
    pattern: str | None = None
    keywords: list[str] = field(default_factory=list)

    def compiled_pattern(self) -> re.Pattern | None:
        return re.compile(self.pattern) if self.pattern else None


_ACTION_ALIASES = {
    "MASK": RedactionAction.FULL_MASK,
    "FULL_MASK": RedactionAction.FULL_MASK,
    "BLUR": RedactionAction.BLUR,
    "PIXELATE": RedactionAction.PIXELATE,
    "PARTIAL_MASK": RedactionAction.PARTIAL_MASK,
}


def load_user_rules(path: str | Path) -> list[UserRule]:
    rules_path = Path(path)
    if not rules_path.exists():
        return []
    raw = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = [raw]

    rules: list[UserRule] = []
    for entry in raw:
        action_raw = str(entry.get("action", "BLUR")).upper()
        rules.append(
            UserRule(
                name=entry["name"],
                action=_ACTION_ALIASES.get(action_raw, RedactionAction.BLUR),
                risk=RiskLevel(str(entry.get("risk", "HIGH")).upper()),
                pattern=entry.get("pattern"),
                keywords=entry.get("keywords", []),
            )
        )
    return rules


class UserRuleDetector:
    def __init__(self, rules: list[UserRule]) -> None:
        self.rules = rules

    def detect(self, tokens: list[OcrToken]) -> list[Detection]:
        if not self.rules:
            return []
        detections: list[Detection] = []
        for line in group_into_lines(tokens):
            index = build_line_index(line)
            normalized = normalize_for_context(index)
            haystack = normalized.normalized_text.lower()
            for rule in self.rules:
                pattern = rule.compiled_pattern()
                if pattern:
                    for match in pattern.finditer(normalized.normalized_text):
                        matched_tokens = normalized.tokens_for_normalized_span(*match.span())
                        if not matched_tokens:
                            continue
                        box = merge_bounding_boxes([t.bounding_box for t in matched_tokens])
                        detections.append(self._make_detection(rule, match.group(0), box))
                for kw in rule.keywords:
                    pos = haystack.find(kw.lower())
                    if pos == -1:
                        continue
                    end = pos + len(kw)
                    matched_tokens = normalized.tokens_for_normalized_span(pos, end)
                    if not matched_tokens:
                        continue
                    box = merge_bounding_boxes([t.bounding_box for t in matched_tokens])
                    detections.append(self._make_detection(rule, kw, box))
        return detections

    def _make_detection(self, rule: UserRule, text: str, box) -> Detection:
        return Detection(
            type=f"UserRule:{rule.name}",
            text=text,
            confidence=0.9,
            bounding_box=box,
            risk_score=_RISK_SCORE[rule.risk],
            risk_level=rule.risk,
            action=rule.action,
            source_layers=["user_rule"],
        )
