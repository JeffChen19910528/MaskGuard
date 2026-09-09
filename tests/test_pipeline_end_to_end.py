"""End-to-end pipeline smoke test using a fake OCR engine, since the real
LocalOcrEngine needs the Tesseract binary installed on the host machine."""
from __future__ import annotations

from PIL import Image, ImageDraw

from maskguard.config import load_config
from maskguard.models import BoundingBox, OcrToken
from maskguard.ocr.base import IOcrEngine
from maskguard.pipeline import Pipeline


class FakeOcrEngine(IOcrEngine):
    """Always returns the same fixed tokens, regardless of image content —
    good enough to exercise the detection->risk->policy->redaction->
    verification wiring without a real OCR dependency."""

    is_cloud = False

    def __init__(self, tokens: list[OcrToken]) -> None:
        self._tokens = tokens

    def recognize(self, image, languages):
        return self._tokens


def _make_tokens() -> list[OcrToken]:
    return [
        OcrToken("Email:", 0.9, BoundingBox(5, 5, 50, 20)),
        OcrToken("john@example.com", 0.9, BoundingBox(60, 5, 150, 20)),
        OcrToken("password:", 0.9, BoundingBox(5, 40, 70, 20)),
        OcrToken("hunter2secret", 0.9, BoundingBox(80, 40, 100, 20)),
    ]


def test_pipeline_processes_image_and_writes_outputs(tmp_path):
    image_path = tmp_path / "input.png"
    image = Image.new("RGB", (300, 100), (255, 255, 255))
    ImageDraw.Draw(image).rectangle((0, 0, 299, 99), outline=(0, 0, 0))
    image.save(image_path)

    config = load_config()
    config.masking.verification = False  # FakeOcrEngine can't "see" the masked pixels meaningfully

    fake_ocr = FakeOcrEngine(_make_tokens())
    pipeline = Pipeline(config, ocr_engine=fake_ocr)

    output_image = tmp_path / "out" / "input_masked.png"
    report_path = tmp_path / "out" / "input_masked.json"
    log_path = tmp_path / "out" / "audit.log"

    result = pipeline.process(str(image_path), str(output_image), str(report_path), str(log_path))

    assert not result.blocked
    assert output_image.exists()
    assert report_path.exists()
    assert log_path.exists()

    types = {d["type"] for d in result.report["detections"]}
    assert "Email" in types
    assert "SecretKeyValue" in types

    # Audit log must never contain the raw sensitive text.
    log_content = log_path.read_text(encoding="utf-8")
    assert "john@example.com" not in log_content
    assert "hunter2secret" not in log_content
