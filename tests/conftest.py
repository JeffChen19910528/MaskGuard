from __future__ import annotations

from maskguard.models import BoundingBox, OcrToken


def tok(text: str, x: int, y: int = 0, width: int | None = None, height: int = 20) -> OcrToken:
    if width is None:
        width = max(10, len(text) * 10)
    return OcrToken(text=text, confidence=0.95, bounding_box=BoundingBox(x=x, y=y, width=width, height=height))


def line(*texts: str, y: int = 0) -> list[OcrToken]:
    tokens = []
    cursor = 0
    for text in texts:
        t = tok(text, x=cursor, y=y)
        tokens.append(t)
        cursor += t.bounding_box.width + 8
    return tokens
