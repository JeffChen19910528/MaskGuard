"""Groups OCR tokens into reading-order lines, engine-agnostic (works for any IOcrEngine)."""
from __future__ import annotations

from .models import OcrToken


def group_into_lines(tokens: list[OcrToken]) -> list[list[OcrToken]]:
    """Group tokens whose bounding boxes vertically overlap into the same line,
    then sort each line left-to-right. Order of lines is top-to-bottom.
    """
    if not tokens:
        return []

    ordered = sorted(tokens, key=lambda t: (t.bounding_box.y, t.bounding_box.x))
    lines: list[list[OcrToken]] = []

    for token in ordered:
        placed = False
        top = token.bounding_box.y
        bottom = top + token.bounding_box.height
        for line in lines:
            line_top = min(t.bounding_box.y for t in line)
            line_bottom = max(t.bounding_box.y + t.bounding_box.height for t in line)
            overlap = min(bottom, line_bottom) - max(top, line_top)
            min_height = min(token.bounding_box.height, line_bottom - line_top)
            if min_height > 0 and overlap / min_height > 0.5:
                line.append(token)
                placed = True
                break
        if not placed:
            lines.append([token])

    for line in lines:
        line.sort(key=lambda t: t.bounding_box.x)

    lines.sort(key=lambda line: min(t.bounding_box.y for t in line))
    return lines


def line_text(line: list[OcrToken]) -> str:
    return " ".join(t.text for t in line)
