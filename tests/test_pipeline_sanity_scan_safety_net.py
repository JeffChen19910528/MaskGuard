"""Phase 6.1 §十五 required security test: simulates the exact Phase 6
benchmark finding (Detection completely misses a sensitive value, e.g.
Passport_low_res / BankAccount_low_res — true_positives == 0) running
through the REAL, unmodified `Pipeline`, and confirms the Whole-Image
Sanity Scan (Phase 6.1 P0-2) prevents a silent PASS.
"""
from __future__ import annotations

from PIL import Image

from maskguard.config import load_config
from maskguard.models import BoundingBox, OcrToken
from maskguard.ocr.base import IOcrEngine
from maskguard.pipeline import Pipeline


class _MissesAtDetectionTimeThenVisibleEngine(IOcrEngine):
    """1st recognize() call (Detection time): returns nothing at all, so the
    Detection layer finds zero candidates — exactly the Phase 6 benchmark's
    Passport_low_res/BankAccount_low_res shape (true_positives == 0). Every
    later call (VerificationEngine's own re-OCR, if any, and the new
    WholeImageSanityScanner's independent pass) returns the real sensitive
    value, because in reality nothing was ever detected or redacted, so of
    course it is still fully visible in the "final" image."""

    is_cloud = False

    def __init__(self, visible_token: OcrToken) -> None:
        self.call_count = 0
        self._visible_token = visible_token

    def recognize(self, image, languages):
        self.call_count += 1
        if self.call_count == 1:
            return []
        return [self._visible_token]


class _AlwaysBlindEngine(IOcrEngine):
    """Never finds anything, ever — simulates a truly clean image (or an
    image whose non-sensitive content OCR just can't read), so BOTH
    Detection and the sanity scan come back empty."""

    is_cloud = False

    def recognize(self, image, languages):
        return []


def _run_pipeline(engine, tmp_path, strict_mode=False):
    config = load_config()
    if strict_mode:
        config.apply_strict_mode()
    pipeline = Pipeline(config, ocr_engine=engine)

    image_path = tmp_path / "input.png"
    Image.new("RGB", (300, 100), (255, 255, 255)).save(image_path)

    return pipeline.process(
        str(image_path),
        str(tmp_path / "out.png"),
        str(tmp_path / "out.json"),
        str(tmp_path / "audit.log"),
    )


def test_detection_miss_of_taiwan_id_is_caught_by_sanity_scan_not_silently_passed(tmp_path):
    visible_token = OcrToken(text="A123456789", confidence=0.95, bounding_box=BoundingBox(0, 0, 100, 20))
    engine = _MissesAtDetectionTimeThenVisibleEngine(visible_token)

    result = _run_pipeline(engine, tmp_path)

    # The exact Phase 6 finding this closes: Detection found nothing, so
    # naive verification would trivially "PASS" — it must not, once the
    # sanity scan independently finds the still-visible TaiwanID.
    assert result.verification.status == "FAILED", (
        "Whole-Image Sanity Scan did not catch a Detection miss of a "
        "critical sensitive type — this is the exact Phase 6 false-PASS bug"
    )
    assert result.verification.needs_human_review is True
    assert "TaiwanID" in result.verification.residual_types


def test_detection_miss_of_credit_card_is_caught_by_sanity_scan(tmp_path):
    visible_token = OcrToken(text="4111 1111 1111 1111", confidence=0.9, bounding_box=BoundingBox(0, 0, 200, 20))
    engine = _MissesAtDetectionTimeThenVisibleEngine(visible_token)

    result = _run_pipeline(engine, tmp_path)

    assert result.verification.status == "FAILED"
    assert "CreditCard" in result.verification.residual_types


def test_strict_mode_blocks_output_when_sanity_scan_catches_a_detection_miss(tmp_path):
    visible_token = OcrToken(text="A123456789", confidence=0.95, bounding_box=BoundingBox(0, 0, 100, 20))
    engine = _MissesAtDetectionTimeThenVisibleEngine(visible_token)

    result = _run_pipeline(engine, tmp_path, strict_mode=True)

    assert result.blocked is True
    assert result.output_path is None  # Strict Mode: image withheld (Skill.md §40)


def test_pipeline_still_passes_normally_when_both_detection_and_sanity_scan_find_nothing(tmp_path):
    """Companion case (§十五): if the whole-image scan ALSO finds nothing,
    a normal PASS must still be reachable — the safety net must not make
    every genuinely-clean image unconditionally fail."""
    engine = _AlwaysBlindEngine()

    result = _run_pipeline(engine, tmp_path)

    assert result.verification.status == "PASSED"
    assert result.verification.needs_human_review is False
    assert not result.blocked
