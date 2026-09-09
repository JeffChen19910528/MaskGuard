"""Shared line-text normalization for Detection layers (Skill.md §10).

P0-2 fix: real OCR (confirmed against Tesseract 5.4 + chi_tra) frequently
returns each Han character as its own separate word-token — "姓名：王小明"
comes back as six tokens: 姓 / 名 / ﹕ / 王 / 小 / 明. `line_matching.
build_line_index` joins ALL tokens with a single space regardless of script,
turning that into "姓 名 ﹕ 王 小 明" — which breaks any literal-substring
match for the label "姓名" even though a human reading the same image sees
one contiguous phrase.

`normalize_for_context()` fixes this generically — no hardcoded label list,
no assumption about which detector uses it:

- known full-width / OCR-presentation punctuation variants collapse to their
  canonical ASCII form ("："/"﹕" -> ":", "，" -> ",", ...).
- the single space `build_line_index` inserts between two OCR tokens is
  dropped when NEITHER side of that boundary is an ASCII letter/digit (i.e.
  it was a token-boundary artifact between two CJK characters or between a
  CJK character and punctuation, not a real word break), and kept as one
  canonical space otherwise (real word boundaries — "TEST DATA", or a label
  directly followed by a Latin/digit value like "身分證: A123456789" — are
  preserved).
- normalization only ever acts *between* the original OCR tokens; it never
  inspects or alters characters inside a single token's own text (so e.g. the
  underscores inside "demo_test_key_123456789", a single token, are never
  touched).

This never permanently loses the token/bounding-box mapping: every character
kept in the normalized text remembers which position in the original
`LineIndex.text` (and therefore which OCR token, via the existing
`tokens_for_span` helper) it came from — see
`NormalizedLineIndex.tokens_for_normalized_span()`. Normalized text, the
original per-token text, and bounding boxes all stay cross-referenceable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import OcrToken
from .line_matching import LineIndex, tokens_for_span

_FULLWIDTH_OFFSET = 0xFEE0
_PUNCTUATION_VARIANTS = {
    "：": ":", "﹕": ":", "︓": ":",
    "；": ";", "﹔": ";",
    "，": ",", "﹐": ",",
    "。": ".", "．": ".",
    "（": "(", "）": ")",
}

_TOKEN_PATTERN = re.compile(r"\S+")


def _normalize_char(ch: str) -> str:
    if ch in _PUNCTUATION_VARIANTS:
        return _PUNCTUATION_VARIANTS[ch]
    code = ord(ch)
    if 0xFF01 <= code <= 0xFF5E:  # fullwidth ASCII block -> halfwidth
        return chr(code - _FULLWIDTH_OFFSET)
    return ch


def _is_ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


@dataclass
class NormalizedLineIndex:
    normalized_text: str
    #: normalized_text[i] was derived from original.text[_source_positions[i]]
    _source_positions: list[int] = field(repr=False)
    original: LineIndex

    def tokens_for_normalized_span(self, start: int, end: int) -> list[OcrToken]:
        """Map a [start, end) span of `normalized_text` back to the original
        OCR tokens that produced it, via their bounding boxes."""
        if not self._source_positions or start >= end:
            return []
        start = max(0, min(start, len(self._source_positions) - 1))
        end = max(start + 1, min(end, len(self._source_positions)))
        orig_start = self._source_positions[start]
        orig_end = self._source_positions[end - 1] + 1
        return tokens_for_span(self.original, orig_start, orig_end)


def normalize_for_context(line_index: LineIndex) -> NormalizedLineIndex:
    text = line_index.text
    out_chars: list[str] = []
    out_positions: list[int] = []
    prev_last_char: str | None = None

    for match in _TOKEN_PATTERN.finditer(text):
        seg_start = match.start()
        raw_segment = match.group(0)
        normalized_segment = [_normalize_char(c) for c in raw_segment]
        if not normalized_segment:
            continue

        first_char = normalized_segment[0]
        if prev_last_char is not None and (_is_ascii_alnum(prev_last_char) or _is_ascii_alnum(first_char)):
            out_chars.append(" ")
            out_positions.append(seg_start)

        for offset, ch in enumerate(normalized_segment):
            out_chars.append(ch)
            out_positions.append(seg_start + offset)

        prev_last_char = normalized_segment[-1]

    return NormalizedLineIndex("".join(out_chars), out_positions, line_index)
