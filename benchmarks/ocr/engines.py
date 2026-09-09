"""OCR engines available to the benchmark, all implementing the SAME
production `maskguard.ocr.base.IOcrEngine` interface — the whole point of
the benchmark is that MaskGuard's Detection/Risk/Policy/Redaction/
Verification layers run completely unmodified against any of them.
"""
from __future__ import annotations

from maskguard.models import BoundingBox, OcrToken
from maskguard.ocr.base import IOcrEngine
from maskguard.ocr.tesseract_engine import LocalOcrEngine

from .env_check import check_paddleocr_available

# Tesseract is MaskGuard's existing, unmodified production OCR engine.
# Named here for benchmark clarity/symmetry with PaddleOcrEngine below —
# this is NOT a new implementation, just `LocalOcrEngine` under a name that
# reads clearly in benchmark result rows ("engine": "Tesseract").
TesseractOcrEngine = LocalOcrEngine


class PaddleOcrEngine(IOcrEngine):
    """PaddleOCR adapter (Skill.md §9 CustomVisionEngine-style pluggability).

    NOT installed/exercised in this benchmark run — PaddleOCR pulls in a
    heavy ML runtime (paddlepaddle + paddleocr, GPU-capable builds are
    hundreds of MB) that risks destabilizing this environment, so it was
    deliberately not pip-installed here. This class exists so the framework
    already supports it: implement-and-drop-in, no changes needed anywhere
    else. Instantiating it without the `paddleocr` package installed raises
    a clear `RuntimeError` rather than failing at import time, so importing
    this module never breaks when PaddleOCR isn't present.
    """

    is_cloud = False

    _LANG_MAP = {"zh-TW": "chinese_cht", "zh-CN": "ch", "en": "en"}

    def __init__(self) -> None:
        available, reason = check_paddleocr_available()
        if not available:
            raise RuntimeError(
                f"PaddleOCR is not installed in this environment ({reason}). "
                "Install `paddleocr` + `paddlepaddle` to use this engine; "
                "TesseractOcrEngine remains fully functional without it."
            )
        from paddleocr import PaddleOCR  # noqa: PLC0415

        # One PaddleOCR instance per language is the library's own model.
        self._readers: dict[str, "PaddleOCR"] = {}

    def _reader_for(self, lang: str):
        if lang not in self._readers:
            from paddleocr import PaddleOCR  # noqa: PLC0415

            self._readers[lang] = PaddleOCR(lang=lang, show_log=False)
        return self._readers[lang]

    def recognize(self, image, languages: list[str]) -> list[OcrToken]:
        lang = self._LANG_MAP.get(languages[0] if languages else "en", "en")
        reader = self._reader_for(lang)

        import numpy as np  # noqa: PLC0415

        result = reader.ocr(np.array(image), cls=False)

        tokens: list[OcrToken] = []
        for line in result or []:
            for entry in line or []:
                quad, (text, confidence) = entry
                xs = [p[0] for p in quad]
                ys = [p[1] for p in quad]
                box = BoundingBox(
                    x=int(min(xs)), y=int(min(ys)),
                    width=int(max(xs) - min(xs)), height=int(max(ys) - min(ys)),
                )
                tokens.append(OcrToken(text=text, confidence=float(confidence), bounding_box=box))
        return tokens
