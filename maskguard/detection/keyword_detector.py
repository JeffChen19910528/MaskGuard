"""Layer 2 — Keyword detection. Keywords never classify data by themselves;
they raise the risk score of nearby values (Skill.md §10 Layer 2, §359).

Scans the normalized line text (see `detection/normalization.py`) so a
multi-character Chinese keyword like "身分證" or "姓名" is still found even
when the OCR engine returned it as one token per Han character — the same
P0-2 tokenization issue ContextDetector was fixed for."""
from __future__ import annotations

from ..models import KeywordHit, OcrToken
from ..textline import group_into_lines
from .line_matching import build_line_index, merge_bounding_boxes
from .normalization import normalize_for_context

# category -> (critical, keywords). Critical categories trigger fail-safe
# handling (§18) when no concrete value can be classified nearby.
_KEYWORDS: dict[str, tuple[bool, list[str]]] = {
    "Credential": (
        True,
        [
            "password", "密碼", "passwd", "pwd", "pin", "api key", "api_key",
            "apikey", "access token", "refresh token", "token", "secret",
            "secret key", "private key", "ssh key", "bearer", "authorization",
            "connection string", "database password", "cloud credential",
            "session id", "cookie",
        ],
    ),
    "PersonalID": (True, ["身分證", "護照", "passport", "居留證", "駕照"]),
    "Financial": (True, ["信用卡", "credit card", "銀行帳號", "bank account", "iban", "銀行卡號"]),
    "PersonalInfo": (
        False,
        ["姓名", "電話", "email", "地址", "生日", "員工編號", "客戶編號", "phone", "address"],
    ),
    "Business": (
        False,
        [
            "internal server", "db server", "production", "內部 ip", "internal ip",
            "database", "internal url", "server", "合約", "報價", "成本",
        ],
    ),
}


class KeywordDetector:
    def detect(self, tokens: list[OcrToken]) -> list[KeywordHit]:
        hits: list[KeywordHit] = []
        for line in group_into_lines(tokens):
            index = build_line_index(line)
            normalized = normalize_for_context(index)
            haystack = normalized.normalized_text.lower()
            for category, (critical, keywords) in _KEYWORDS.items():
                for kw in keywords:
                    start = 0
                    kw_lower = kw.lower()
                    while True:
                        pos = haystack.find(kw_lower, start)
                        if pos == -1:
                            break
                        end = pos + len(kw_lower)
                        matched_tokens = normalized.tokens_for_normalized_span(pos, end)
                        if matched_tokens:
                            box = merge_bounding_boxes([t.bounding_box for t in matched_tokens])
                            hits.append(
                                KeywordHit(
                                    keyword=kw, category=category, critical=critical, bounding_box=box
                                )
                            )
                        start = end
        return hits
