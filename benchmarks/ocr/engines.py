"""OCR engines available to the benchmark, all implementing the SAME
production `maskguard.ocr.base.IOcrEngine` interface — the whole point of
the benchmark is that MaskGuard's Detection/Risk/Policy/Redaction/
Verification layers run completely unmodified against any of them.

Both adapters below are re-exported straight from `maskguard.ocr` (Phase 7):
this module does not implement OCR engines itself, it only names them for
benchmark-row clarity/symmetry ("engine": "Tesseract" / "PaddleOCR").
"""
from __future__ import annotations

from maskguard.ocr.paddle_engine import PaddleOcrEngine
from maskguard.ocr.tesseract_engine import LocalOcrEngine

from .env_check import check_paddleocr_available

# Tesseract is MaskGuard's existing, unmodified production OCR engine.
TesseractOcrEngine = LocalOcrEngine

__all__ = ["TesseractOcrEngine", "PaddleOcrEngine", "check_paddleocr_available"]
