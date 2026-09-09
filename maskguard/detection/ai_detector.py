"""Layer 4 — Local AI classification (Skill.md §10 Layer 4, §31 IAiDetector, §32
Local AI Mode). This never has final say on redaction — everything it emits is
advisory input to the Risk/Policy Engine (Skill.md §41), and low-confidence
output is marked `unknown=True` so fail-safe handling (§18) can kick in.

This module is a placeholder-quality local heuristic classifier: a common
Chinese-surname matcher for bare personal names, plus a Shannon-entropy check
for opaque secret-looking strings near credential keywords. Swap in a real
local model behind the same `IAiClassifier.detect()` signature later.
"""
from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from collections import Counter

from ..models import Detection, KeywordHit, OcrToken
from ..textline import group_into_lines
from .line_matching import build_line_index, tokens_for_span

_COMMON_SURNAMES = (
    "陳林黃張李王吳劉蔡楊許鄭謝洪郭邱曾廖賴徐周葉蘇莊呂江何蕭羅高潘"
    "簡朱鍾游詹方蔣顏薰盧汪戴葛"
)
_NAME_PATTERN = re.compile(f"[{_COMMON_SURNAMES}][一-鿿]{{1,2}}")

_MIN_SECRET_LEN = 16
_MIN_ENTROPY = 3.2


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = Counter(text)
    length = len(text)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


class IAiClassifier(ABC):
    """Local/Cloud AI providers implement this (Skill.md §31)."""

    is_cloud: bool = False

    @abstractmethod
    def detect(self, tokens: list[OcrToken], keyword_hits: list[KeywordHit]) -> list[Detection]:
        raise NotImplementedError


class LocalAiDetector(IAiClassifier):
    is_cloud = False

    def detect(self, tokens: list[OcrToken], keyword_hits: list[KeywordHit]) -> list[Detection]:
        detections: list[Detection] = []
        detections.extend(self._detect_bare_names(tokens))
        detections.extend(self._detect_opaque_secrets(tokens, keyword_hits))
        return detections

    def _detect_bare_names(self, tokens: list[OcrToken]) -> list[Detection]:
        detections: list[Detection] = []
        for line in group_into_lines(tokens):
            index = build_line_index(line)
            for match in _NAME_PATTERN.finditer(index.text):
                matched_tokens = tokens_for_span(index, *match.span())
                if not matched_tokens:
                    continue
                box = matched_tokens[0].bounding_box
                detections.append(
                    Detection(
                        type="PersonalName",
                        text=match.group(0),
                        confidence=0.45,
                        bounding_box=box,
                        source_layers=["ai"],
                        unknown=True,
                    )
                )
        return detections

    def _detect_opaque_secrets(
        self, tokens: list[OcrToken], keyword_hits: list[KeywordHit]
    ) -> list[Detection]:
        if not keyword_hits:
            return []
        detections: list[Detection] = []
        critical_lines_y = {
            (hit.bounding_box.y, hit.bounding_box.y + hit.bounding_box.height)
            for hit in keyword_hits
            if hit.category == "Credential"
        }
        for token in tokens:
            if len(token.text) < _MIN_SECRET_LEN:
                continue
            if _shannon_entropy(token.text) < _MIN_ENTROPY:
                continue
            tok_top = token.bounding_box.y
            tok_bottom = tok_top + token.bounding_box.height
            near_credential_keyword = any(
                min(tok_bottom, kw_bottom) - max(tok_top, kw_top) > 0
                for (kw_top, kw_bottom) in critical_lines_y
            )
            if not near_credential_keyword:
                continue
            detections.append(
                Detection(
                    type="OpaqueSecret",
                    text=token.text,
                    confidence=0.5,
                    bounding_box=token.bounding_box,
                    source_layers=["ai"],
                    unknown=True,
                )
            )
        return detections
