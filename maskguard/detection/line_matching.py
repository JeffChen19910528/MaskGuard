"""Shared helper: build a searchable line string from OCR tokens and map regex
match spans back to the bounding boxes of the tokens that produced them.
Needed because sensitive values (credit card numbers, phone numbers) are often
split across multiple OCR word-tokens separated by spaces.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import BoundingBox, OcrToken


@dataclass
class LineIndex:
    text: str
    token_spans: list[tuple[int, int, OcrToken]]  # (start, end, token) in `text`


def build_line_index(line: list[OcrToken]) -> LineIndex:
    parts: list[str] = []
    spans: list[tuple[int, int, OcrToken]] = []
    cursor = 0
    for i, token in enumerate(line):
        if i > 0:
            parts.append(" ")
            cursor += 1
        start = cursor
        parts.append(token.text)
        cursor += len(token.text)
        spans.append((start, cursor, token))
    return LineIndex(text="".join(parts), token_spans=spans)


def tokens_for_span(index: LineIndex, start: int, end: int) -> list[OcrToken]:
    return [tok for (s, e, tok) in index.token_spans if s < end and e > start]


def merge_bounding_boxes(boxes: list[BoundingBox]) -> BoundingBox:
    if not boxes:
        raise ValueError("no boxes to merge")
    left = min(b.x for b in boxes)
    top = min(b.y for b in boxes)
    right = max(b.x + b.width for b in boxes)
    bottom = max(b.y + b.height for b in boxes)
    return BoundingBox(x=left, y=top, width=right - left, height=bottom - top)
