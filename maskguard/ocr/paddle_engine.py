"""PaddleOCR adapter (Skill.md §9: multi-engine, replaceable, never bound to
one provider). Local OCR only: the image never leaves the machine
(`is_cloud = False`, the same offline contract `LocalOcrEngine`/Tesseract
gives — Strict Mode, Skill.md §40, treats both identically).

NOT the production default (see the Phase 7 benchmark report for why
Tesseract stays default) — this class exists so MaskGuard's `IOcrEngine`
abstraction already supports PaddleOCR as a genuine drop-in alternative,
with zero changes anywhere else in Detection/Risk/Policy/Redaction/
Verification: every one of those layers only ever sees the shared
`OcrToken` model, never a PaddleOCR-specific result object.

Importing this module never requires `paddleocr`/`paddlepaddle` to be
installed — only instantiating `PaddleOcrEngine` does, and it raises a
clear `RuntimeError` up front rather than failing deep inside
`.recognize()`, so `LocalOcrEngine` (Tesseract) stays fully usable without
either package present.
"""
from __future__ import annotations

import logging

from ..models import BoundingBox, OcrToken
from .base import IOcrEngine

# PaddleOCR 3.x language codes. "chinese_cht" is a genuinely distinct,
# Traditional-Chinese-aware configuration — verified empirically against
# this project's Traditional Chinese fixtures (see Phase 7 report §6), NOT
# assumed to just reuse Simplified-Chinese ("ch") accuracy. Both currently
# route through the same underlying "PP-OCRv6_medium_rec" model file:
# PaddleOCR's PP-OCRv6 generation ships one unified multilingual
# recognition model covering 100+ scripts (including Traditional Chinese)
# rather than one separate model per language the way older PP-OCRv3/v4
# did — `lang=` still selects Traditional-Chinese-aware detection/decoding
# behavior, it just isn't a *separate weights file* for this model
# generation. Recognition accuracy against this project's chi_tra fixtures
# was verified directly, not inferred from the model-file name.
_LANG_MAP = {"zh-TW": "chinese_cht", "zh-CN": "ch", "en": "en"}


def is_available() -> tuple[bool, str | None]:
    """(available, reason_if_not). Never installs or modifies anything."""
    try:
        import paddleocr  # noqa: F401,PLC0415
    except ImportError as exc:
        return False, f"paddleocr package not importable: {exc}"
    return True, None


class PaddleOcrEngine(IOcrEngine):
    is_cloud = False

    def __init__(self) -> None:
        available, reason = is_available()
        if not available:
            raise RuntimeError(
                f"PaddleOCR is not installed in this environment ({reason}). "
                "Install `paddleocr` + `paddlepaddle` to use this engine; "
                "LocalOcrEngine (Tesseract) remains fully functional without it."
            )
        logging.getLogger("paddlex").setLevel(logging.ERROR)
        # One PaddleOCR pipeline instance per language — the library's own
        # model handle, lazily created and cached per language on first use.
        # A caller that reuses one PaddleOcrEngine across many images (e.g.
        # Pipeline) pays PaddleOCR's model-load ("cold start") cost once per
        # language, never once per image (see Phase 7 report §Cold Start vs
        # Warm Run).
        self._readers: dict[str, object] = {}

    def _reader_for(self, lang: str):
        if lang not in self._readers:
            from paddleocr import PaddleOCR  # noqa: PLC0415

            # enable_mkldnn=False works around a confirmed PP-OCRv6 text-
            # detection crash under paddlepaddle 3.3.1's default oneDNN/PIR
            # CPU executor on Windows (NotImplementedError:
            # "ConvertPirAttribute2RuntimeAttribute not support
            # [pir::ArrayAttribute<pir::DoubleAttribute>]") — a confirmed
            # paddlepaddle/PaddleX CPU-executor bug on this environment, not
            # a MaskGuard workaround for PaddleOCR's detection ACCURACY (see
            # Phase 7 report §Environment for the full repro/root cause).
            #
            # return_word_box=True asks PaddleOCR for its own per-word
            # segmentation (genuine model output — CTC-decode word
            # alignment — not something this adapter invents) so OcrToken
            # granularity is comparable to Tesseract's word-level tokens
            # instead of one giant token per detected text LINE.
            #
            # use_doc_orientation_classify/use_doc_unwarping/
            # use_textline_orientation=False: PaddleOCR's default pipeline
            # silently runs its OWN extra page-rotation-correction stages
            # (document orientation classification, document unwarping,
            # per-line orientation correction) before text detection even
            # starts. Leaving those on would mean PaddleOCR gets *additional*
            # preprocessing Tesseract never receives — MaskGuard's shared
            # `deskew_for_ocr()` (preprocessing.py) is the ONLY preprocessing
            # step both engines are meant to see (Phase 7 report §8: "same
            # preprocessing for both engines" is the controlled variable this
            # benchmark exists to isolate OCR ENGINE choice from). Disabling
            # PaddleOCR's own preprocessing keeps that comparison fair in
            # both directions — it is not "helping" or "hurting" PaddleOCR,
            # it is removing an uncontrolled experimental variable.
            self._readers[lang] = PaddleOCR(
                lang=lang,
                enable_mkldnn=False,
                return_word_box=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._readers[lang]

    def recognize(self, image, languages: list[str]) -> list[OcrToken]:
        lang = _LANG_MAP.get(languages[0] if languages else "en", "en")
        reader = self._reader_for(lang)

        import numpy as np  # noqa: PLC0415

        results = reader.predict(np.array(image.convert("RGB")))

        tokens: list[OcrToken] = []
        for result in results or []:
            rec_texts = result.get("rec_texts") or []
            rec_scores = result.get("rec_scores") or []
            word_texts = result.get("text_word") or []
            word_boxes = result.get("text_word_boxes") or []
            rec_boxes = result.get("rec_boxes")

            for i, line_text in enumerate(rec_texts):
                confidence = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                words = word_texts[i] if i < len(word_texts) else None
                boxes = word_boxes[i] if i < len(word_boxes) else None

                if words and boxes is not None and len(words) == len(boxes):
                    for word_text, box in zip(words, boxes):
                        word_text = word_text.strip()
                        if not word_text:
                            continue
                        x0, y0, x1, y1 = (int(v) for v in box)
                        tokens.append(
                            OcrToken(
                                text=word_text,
                                confidence=confidence,
                                bounding_box=BoundingBox(
                                    x=x0, y=y0, width=max(0, x1 - x0), height=max(0, y1 - y0)
                                ),
                            )
                        )
                else:
                    # No per-word segmentation for this line (e.g.
                    # return_word_box unsupported for this model/lang) —
                    # fall back to one line-level token rather than
                    # silently dropping recognized text.
                    stripped = line_text.strip()
                    if not stripped:
                        continue
                    if rec_boxes is not None and i < len(rec_boxes):
                        x0, y0, x1, y1 = (int(v) for v in rec_boxes[i])
                        box = BoundingBox(x=x0, y=y0, width=max(0, x1 - x0), height=max(0, y1 - y0))
                    else:
                        box = BoundingBox(x=0, y=0, width=0, height=0)
                    tokens.append(OcrToken(text=stripped, confidence=confidence, bounding_box=box))
        return tokens
