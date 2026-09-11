"""Phase 7: PaddleOCR adapter (`maskguard.ocr.paddle_engine.PaddleOcrEngine`)
conformance tests. Everything except the "not installed" error-handling test
requires `paddleocr`/`paddlepaddle` actually importable in THIS interpreter
— gated by the session-scoped `paddle_env` fixture (tests/ocr_benchmark/
conftest.py), same skip-with-reason pattern `tesseract_env` already uses for
Tesseract. See the Phase 7 report for why PaddleOCR runs from an isolated
venv rather than this repo's main environment (§Isolation).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from maskguard.models import OcrToken
from maskguard.ocr.base import IOcrEngine
from maskguard.ocr.paddle_engine import PaddleOcrEngine, is_available

_DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "results" / "dataset"


def _fixture(name: str) -> Image.Image:
    path = _DATASET_DIR / name
    if not path.exists():
        pytest.skip(f"missing benchmark fixture {name} — run: python -m benchmarks.ocr.run")
    return Image.open(path).convert("RGB")


# ---------------------------------------------------------------------------
# 10: error handling — must run unconditionally, including WITHOUT PaddleOCR
# installed (that's the actual case this repo's main environment is in).
# ---------------------------------------------------------------------------


def test_instantiation_raises_clear_error_when_paddleocr_not_installed():
    available, _ = is_available()
    if available:
        pytest.skip("paddleocr IS importable in this interpreter — nothing to assert here")
    with pytest.raises(RuntimeError, match="PaddleOCR is not installed"):
        PaddleOcrEngine()


def test_module_import_never_requires_paddleocr_installed():
    # Regression guard: importing the module must not itself import
    # paddleocr/paddlepaddle at module scope — only instantiating the class
    # (or calling .recognize()) should require them.
    import importlib

    module = importlib.import_module("maskguard.ocr.paddle_engine")
    assert hasattr(module, "PaddleOcrEngine")


# ---------------------------------------------------------------------------
# 1: interface compliance
# ---------------------------------------------------------------------------


def test_paddle_engine_implements_iocrengine_interface(paddle_env):
    engine = PaddleOcrEngine()
    assert isinstance(engine, IOcrEngine)
    assert engine.is_cloud is False


# ---------------------------------------------------------------------------
# 2/3/9: OCR result conversion, bbox validity, confidence handling
# ---------------------------------------------------------------------------


def test_recognize_returns_ocrtoken_list_with_valid_fields(paddle_env):
    engine = PaddleOcrEngine()
    image = _fixture("Email_clean.png")
    tokens = engine.recognize(image, ["en"])

    assert tokens, "expected at least one OcrToken from a clean Email fixture"
    for token in tokens:
        assert isinstance(token, OcrToken)
        assert isinstance(token.text, str) and token.text.strip() == token.text and token.text
        assert 0.0 <= token.confidence <= 1.0
        box = token.bounding_box
        assert box.width >= 0 and box.height >= 0
        assert box.x >= 0 and box.y >= 0
        assert box.x + box.width <= image.width
        assert box.y + box.height <= image.height


def test_recognize_reads_the_expected_email_text(paddle_env):
    engine = PaddleOcrEngine()
    image = _fixture("Email_clean.png")
    tokens = engine.recognize(image, ["en"])
    joined = " ".join(t.text for t in tokens).lower()
    assert "example" in joined


# ---------------------------------------------------------------------------
# 4/5/6: Traditional Chinese, English, mixed language
# ---------------------------------------------------------------------------


def test_recognize_reads_traditional_chinese_taiwan_id_fixture(paddle_env):
    engine = PaddleOcrEngine()
    image = _fixture("TaiwanID_clean.png")
    tokens = engine.recognize(image, ["zh-TW"])
    joined = "".join(t.text for t in tokens)

    assert "A123456789" in joined.replace(" ", "")
    has_cjk = any("一" <= ch <= "鿿" for ch in joined)
    assert has_cjk, "expected at least one recognized Traditional Chinese character"


def test_recognize_reads_mixed_chinese_english_fixture(paddle_env):
    engine = PaddleOcrEngine()
    image = _fixture("mixed_chinese_english.png")
    tokens = engine.recognize(image, ["zh-TW"])
    joined = "".join(t.text for t in tokens)

    has_latin = any(ch.isascii() and ch.isalpha() for ch in joined)
    has_cjk = any("一" <= ch <= "鿿" for ch in joined)
    assert has_latin, "expected at least one Latin-script character"
    assert has_cjk, "expected at least one CJK character"


# ---------------------------------------------------------------------------
# 7/8: empty image, multiple text regions
# ---------------------------------------------------------------------------


def test_recognize_returns_empty_list_for_blank_image(paddle_env):
    engine = PaddleOcrEngine()
    blank = Image.new("RGB", (200, 100), (255, 255, 255))
    tokens = engine.recognize(blank, ["en"])
    assert tokens == []


def test_recognize_finds_multiple_regions_in_multi_sensitive_image(paddle_env):
    engine = PaddleOcrEngine()
    image = _fixture("multiple_sensitive_values.png")
    tokens = engine.recognize(image, ["zh-TW"])

    # Six distinct lines of sensitive data stacked vertically — bounding
    # boxes must be spread across multiple distinct y positions, not
    # collapsed onto one.
    assert len(tokens) > 5
    distinct_y_bands = {token.bounding_box.y // 20 for token in tokens}
    assert len(distinct_y_bands) >= 4, f"expected tokens spread across multiple lines, got y-bands {distinct_y_bands}"
