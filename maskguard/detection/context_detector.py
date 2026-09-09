"""Layer 3 — Context detection. A value with no fixed format (e.g. a bare name)
becomes classifiable once its preceding label is known (Skill.md §10 Layer 3,
example: "姓名：王小明").

Matches against the normalized line text (see `detection/normalization.py`)
rather than the raw OCR-token join, so a Chinese label split by the OCR
engine into one token per character (e.g. "姓","名","﹕","王","小","明") is
still recognized as the contiguous phrase "姓名:王小明" — this was a
confirmed false negative against real Tesseract chi_tra output (P0-2)."""
from __future__ import annotations

import re

from ..models import Detection, OcrToken
from ..textline import group_into_lines
from .line_matching import build_line_index, merge_bounding_boxes
from .normalization import normalize_for_context

_LABEL_TYPE = {
    "姓名": "PersonalName",
    "name": "PersonalName",
    "電話": "Phone",
    "phone": "Phone",
    "tel": "Phone",
    "地址": "Address",
    "address": "Address",
    "生日": "Birthday",
    "birthday": "Birthday",
    "dob": "Birthday",
    "email": "Email",
    "身分證": "TaiwanID",
    "護照": "Passport",
    "passport": "Passport",
    "銀行帳號": "BankAccount",
    "bank account": "BankAccount",
    "員工編號": "EmployeeID",
    "客戶編號": "CustomerID",
}

_LABEL_PATTERN = re.compile(
    r"(?i)(" + "|".join(re.escape(k) for k in _LABEL_TYPE) + r")\s*[:：]\s*(\S.*)"
)


class ContextDetector:
    def detect(self, tokens: list[OcrToken]) -> list[Detection]:
        detections: list[Detection] = []
        for line in group_into_lines(tokens):
            index = build_line_index(line)
            normalized = normalize_for_context(index)
            match = _LABEL_PATTERN.search(normalized.normalized_text)
            if not match:
                continue
            label = match.group(1).lower()
            value_start, value_end = match.span(2)
            value = match.group(2).strip()
            if not value:
                continue
            data_type = _LABEL_TYPE.get(label, "Unknown")

            matched_tokens = normalized.tokens_for_normalized_span(value_start, value_end)
            if not matched_tokens:
                continue
            box = merge_bounding_boxes([t.bounding_box for t in matched_tokens])
            detections.append(
                Detection(
                    type=data_type,
                    text=value,
                    confidence=0.75,
                    bounding_box=box,
                    source_layers=["context"],
                )
            )
        return detections
