"""Local OCR via Tesseract. Image never leaves the machine (Skill.md §9 Offline Mode)."""
from __future__ import annotations

import pytesseract
from PIL.Image import Image
from pytesseract import Output

from ..models import BoundingBox, OcrToken
from .base import IOcrEngine

_LANG_MAP = {
    "zh-TW": "chi_tra",
    "zh-CN": "chi_sim",
    "en": "eng",
}


class LocalOcrEngine(IOcrEngine):
    is_cloud = False

    def __init__(self, tesseract_cmd: str | None = None) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def _lang_string(self, languages: list[str]) -> str:
        codes = [_LANG_MAP.get(lang, lang) for lang in languages]
        return "+".join(codes) if codes else "eng"

    #: Phase 9.3: Tesseract's default PSM (3, fully automatic page
    #: segmentation) was found — via the Phase 9.2 investigation
    #: (docs/ocr-boundary-investigation.md) — to sometimes merge a
    #: label-adjacent punctuation character directly onto a sensitive value
    #: token (e.g. ":PA1234567" as one token instead of ":" + "PA1234567"),
    #: which can defeat token-boundary-sensitive detection. PSM 6 ("assume
    #: a single uniform block of text") was verified, across the complete
    #: existing 51-image benchmark, to fix that tokenization with zero
    #: fixture-level regressions (see docs/ocr-boundary-investigation.md
    #: §12 for the full comparison). Only this one Tesseract config flag
    #: changes here — language, OEM, and every other call argument are
    #: untouched.
    _TESSERACT_CONFIG = "--psm 6"

    def recognize(self, image: Image, languages: list[str]) -> list[OcrToken]:
        lang = self._lang_string(languages)
        data = pytesseract.image_to_data(
            image, lang=lang, config=self._TESSERACT_CONFIG, output_type=Output.DICT
        )

        tokens: list[OcrToken] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = data["text"][i].strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][i]) / 100.0
            except (ValueError, TypeError):
                confidence = 0.0
            if confidence < 0:
                confidence = 0.0
            box = BoundingBox(
                x=int(data["left"][i]),
                y=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
            )
            tokens.append(OcrToken(text=text, confidence=confidence, bounding_box=box))
        return tokens
