"""Phase 9.2 EXPERIMENTAL ONLY — an OCR engine that accepts an explicit
Tesseract `config` string (PSM/OEM), for diagnosing whether a
configuration-only change could affect the Passport_clean.png finding.

This is a STANDALONE class, not a subclass of
`maskguard.ocr.tesseract_engine.LocalOcrEngine` and not imported by any
production module. `maskguard/ocr/tesseract_engine.py` is NEVER modified
or monkey-patched by this file — production's `LocalOcrEngine` continues
to call `pytesseract.image_to_data()` with no `config=` override,
completely unaffected by anything here. The token-construction logic
below is deliberately a byte-for-byte copy of `LocalOcrEngine.recognize()`
so that ONLY the `config=` argument differs between a production run and
an experimental run — isolating that one variable.
"""
from __future__ import annotations

import pytesseract
from PIL.Image import Image
from pytesseract import Output

from maskguard.models import BoundingBox, OcrToken
from maskguard.ocr.base import IOcrEngine

_LANG_MAP = {
    "zh-TW": "chi_tra",
    "zh-CN": "chi_sim",
    "en": "eng",
}


class ConfigurableTesseractEngine(IOcrEngine):
    """Same token-construction as production `LocalOcrEngine`, but accepts
    an explicit `--psm`/`--oem` (or any other) Tesseract config string.
    EXPERIMENTAL — see module docstring."""

    is_cloud = False

    def __init__(self, tesseract_config: str = "") -> None:
        self.tesseract_config = tesseract_config

    def _lang_string(self, languages: list[str]) -> str:
        codes = [_LANG_MAP.get(lang, lang) for lang in languages]
        return "+".join(codes) if codes else "eng"

    def recognize(self, image: Image, languages: list[str]) -> list[OcrToken]:
        lang = self._lang_string(languages)
        data = pytesseract.image_to_data(
            image, lang=lang, config=self.tesseract_config, output_type=Output.DICT
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
