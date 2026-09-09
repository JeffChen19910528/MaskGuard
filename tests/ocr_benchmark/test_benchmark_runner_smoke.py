"""Benchmark framework smoke test: the runner produces well-formed rows
against every real MaskGuard stage, using a FAKE OCR engine (no Tesseract
needed) so this always runs under `pytest -m benchmark` regardless of the
host's OCR installation."""
from __future__ import annotations

from maskguard.config import load_config
from maskguard.models import OcrToken
from maskguard.ocr.base import IOcrEngine

from benchmarks.ocr.dataset import DatasetItem, SensitiveRegion, render_line
from benchmarks.ocr.runner import run_item


class _GroundTruthEchoEngine(IOcrEngine):
    """Returns tokens that exactly echo the ground-truth text, split on
    whitespace — a "perfect OCR" stand-in so the runner's own mechanics
    (timing, metric computation, verification wiring) can be tested without
    depending on real OCR accuracy at all."""

    is_cloud = False

    def __init__(self, text: str) -> None:
        self._text = text

    def recognize(self, image, languages) -> list[OcrToken]:
        from maskguard.models import BoundingBox

        tokens = []
        cursor = 0
        for word in self._text.split(" "):
            tokens.append(OcrToken(text=word, confidence=0.99, bounding_box=BoundingBox(cursor, 0, len(word) * 10, 20)))
            cursor += len(word) * 10 + 5
        return tokens


def test_run_item_produces_well_formed_row(tmp_path):
    text = "身分證：A123456789"
    image, bbox = render_line(text)
    image_path = tmp_path / "item.png"
    image.save(image_path)

    item = DatasetItem(
        image="item.png", category="TaiwanID", condition="clean", text=text,
        sensitive=[SensitiveRegion(type="TaiwanID", bbox=bbox)],
    )
    config = load_config()
    engine = _GroundTruthEchoEngine("身分證：A123456789")  # simplistic echo, not position-accurate

    row = run_item(engine, "FakeEcho", item, str(image_path), config)

    assert row.engine == "FakeEcho"
    assert row.image == "item.png"
    assert row.category == "TaiwanID"
    assert row.condition == "clean"
    assert isinstance(row.cer, float)
    assert isinstance(row.text_accuracy, float)
    assert row.ocr_time_s >= 0
    assert row.detect_time_s >= 0
    assert row.redact_verify_time_s >= 0
    assert row.total_time_s >= row.ocr_time_s
    assert row.verification_status in ("PASSED", "FAILED", "SKIPPED")
    assert isinstance(row.verification_false_pass, bool)


def test_run_item_reports_false_negative_when_ocr_finds_nothing(tmp_path):
    text = "身分證：A123456789"
    image, bbox = render_line(text)
    image_path = tmp_path / "item.png"
    image.save(image_path)

    item = DatasetItem(
        image="item.png", category="TaiwanID", condition="clean", text=text,
        sensitive=[SensitiveRegion(type="TaiwanID", bbox=bbox)],
    )
    config = load_config()
    engine = _GroundTruthEchoEngine("")  # OCR finds nothing at all

    row = run_item(engine, "BlindEngine", item, str(image_path), config)

    assert row.false_negatives == 1
    assert row.true_positives == 0
    assert row.recall == 0.0


def test_run_item_catches_undetected_value_via_sanity_scan_not_false_pass(tmp_path):
    """Mirrors the exact Phase 6 benchmark finding (confirmed against real
    Tesseract on rotated/blurred/low-res images of Passport/BankAccount): if
    detection completely misses a sensitive value, nothing gets redacted.

    Pre-Phase-6.1: VerificationEngine trivially reported PASSED (zero
    detections to check), and only `run_item`'s own independent re-check
    caught the leak as a `verification_false_pass`.

    Phase 6.1 P0-2: `run_item` now also runs the same Whole-Image Sanity
    Scan `Pipeline.process()` does, so this case is caught EARLIER —
    `verification_status` itself becomes "FAILED" — and the independent
    `verification_false_pass` re-check correctly does NOT additionally fire,
    since its own guard only re-checks when `verification.status == "PASSED"`.
    This test was updated (not just left passing) specifically because the
    P0-2 fix changed which check catches this scenario — see
    test_pipeline_sanity_scan_safety_net.py for the equivalent full-Pipeline
    regression test.
    """
    text = "身分證：A123456789"
    image, bbox = render_line(text)
    image_path = tmp_path / "item.png"
    image.save(image_path)

    item = DatasetItem(
        image="item.png", category="TaiwanID", condition="clean", text=text,
        sensitive=[SensitiveRegion(type="TaiwanID", bbox=bbox)],
    )
    config = load_config()

    class _MissesAtDetectionTimeThenVisibleEngine(IOcrEngine):
        """1st recognize() call (detection time): returns nothing, so the
        Detection layer finds no TaiwanID at all. Every later call
        (verification's own re-OCR, and the runner's independent False-PASS
        re-check) returns the ID — because in reality nothing was ever
        redacted, so of course it's still fully visible."""

        is_cloud = False

        def __init__(self) -> None:
            self.call_count = 0

        def recognize(self, image, languages):
            from maskguard.models import BoundingBox

            self.call_count += 1
            if self.call_count == 1:
                return []
            return [OcrToken(text="A123456789", confidence=0.95, bounding_box=BoundingBox(0, 0, 100, 20))]

    engine = _MissesAtDetectionTimeThenVisibleEngine()
    ground_truth_values = [{"type": "TaiwanID", "value": "A123456789"}]

    row = run_item(engine, "PartialEngine", item, str(image_path), config, ground_truth_values)

    assert row.true_positives == 0
    assert row.false_negatives == 1
    assert row.verification_status == "FAILED"  # caught by the sanity scan
    assert row.sanity_scan_triggered is True
    assert "TaiwanID" in row.sanity_scan_found_types
    assert row.verification_false_pass is False  # not needed — caught earlier
