from __future__ import annotations

from maskguard.models import BoundingBox, OcrToken

# Phase 10.6: exposes `redis_container`/`redis_url`/`redis_namespace` to
# every test in the tree (mirrors how `ocr_env` is available via
# tests/api/conftest.py) — a real, ephemeral Redis container, skipped
# (not failed) when Docker is unavailable.
pytest_plugins = ["tests.redis_env"]


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
