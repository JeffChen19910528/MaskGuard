"""Phase 9.3: a focused, boundary-level test asserting `LocalOcrEngine`
actually passes the production PSM 6 configuration to Tesseract — proving
the intended one-line production change (docs/ocr-boundary-investigation.md)
took effect, without re-testing OCR/Detection behavior itself (that's
covered by the e2e/benchmark suites, which need a real Tesseract binary).

Only the third-party `pytesseract.image_to_data` call is stubbed here —
the boundary between MaskGuard and the external OCR library — never any
MaskGuard code. `LocalOcrEngine.recognize()` itself runs for real, against
the stub's returned data, exercising its actual token-construction logic.
"""
from __future__ import annotations

from unittest.mock import patch

from maskguard.ocr.tesseract_engine import LocalOcrEngine


def test_recognize_passes_psm_6_to_tesseract():
    fake_data = {
        "text": ["PA1234567"],
        "conf": ["90"],
        "left": [10],
        "top": [10],
        "width": [80],
        "height": [20],
    }
    with patch("maskguard.ocr.tesseract_engine.pytesseract.image_to_data", return_value=fake_data) as mock_call:
        engine = LocalOcrEngine()
        tokens = engine.recognize(image=object(), languages=["zh-TW", "en"])

    assert mock_call.call_count == 1
    _, kwargs = mock_call.call_args
    assert kwargs["config"] == "--psm 6"
    assert kwargs["lang"] == "chi_tra+eng"  # unrelated argument, unchanged

    # The real token-construction path still ran against the stubbed data.
    assert len(tokens) == 1
    assert tokens[0].text == "PA1234567"
