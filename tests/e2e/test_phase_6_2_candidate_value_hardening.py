"""Phase 6.2 security regression: the 4 real fixtures that produced a
Verification False PASS in Phase 6.1 (Passport_low_res, BankAccount_low_res,
BankAccount_blurred, BankAccount_rotated) via the REAL, full `Pipeline` and
real Tesseract OCR, using the benchmark's own generated dataset images.

Result: CandidateValueDetector catches these at the MAIN Detection stage
(not just the WholeImageSanityScanner safety net) — Policy Engine's
existing fail-safe path (`_ALWAYS_FAIL_SAFE_TYPES`, unmodified) forces
FULL_MASK, Redaction genuinely masks the value, and Verification correctly
reports PASSED because there is no longer any residual to find. That is a
TRUE pass, not the previous false one — confirmed here by an independent
re-OCR of the actual output file, not just trusting the pipeline's own verdict.
"""
from __future__ import annotations

import pytest

from maskguard.config import load_config
from maskguard.ocr.tesseract_engine import LocalOcrEngine
from maskguard.pipeline import Pipeline

pytestmark = pytest.mark.e2e

_FIXTURES = [
    ("BankAccount_low_res.png", "BankAccount", "1234567890123"),
    ("BankAccount_blurred.png", "BankAccount", "1234567890123"),
    ("BankAccount_rotated.png", "BankAccount", "1234567890123"),
    ("Passport_low_res.png", "Passport", "PA1234567"),
]


@pytest.fixture(scope="module")
def dataset_dir():
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "results" / "dataset"
    if not path.exists():
        pytest.skip("benchmark dataset not generated — run: python -m benchmarks.ocr.run")
    return path


@pytest.mark.parametrize("fixture_name,expected_type,raw_value", _FIXTURES)
def test_previously_false_passing_fixture_now_genuinely_redacted(
    ocr_env, dataset_dir, fixture_name, expected_type, raw_value, tmp_path
):
    from PIL import Image

    config = load_config()
    pipeline = Pipeline(config)

    input_path = dataset_dir / fixture_name
    if not input_path.exists():
        pytest.skip(f"missing benchmark fixture {fixture_name} — regenerate the dataset")

    output_image = tmp_path / "out.png"
    result = pipeline.process(
        str(input_path), str(output_image), str(tmp_path / "out.json"), str(tmp_path / "audit.log")
    )

    detections = result.report["detections"]
    matching = [d for d in detections if d["type"] == expected_type]
    assert matching, f"{fixture_name}: {expected_type} was not detected at all"
    assert matching[0]["action"] == "FULL_MASK", (
        f"{fixture_name}: {expected_type} must resolve to FULL_MASK, was {matching[0]['action']}"
    )

    assert result.verification.status == "PASSED"
    assert not result.blocked

    # Independent re-OCR of the actual output file — not reusing the
    # pipeline's own verdict — confirms the raw value is genuinely gone.
    redacted_tokens = LocalOcrEngine().recognize(Image.open(output_image).convert("RGB"), ["zh-TW", "en"])
    recovered_text = " ".join(t.text for t in redacted_tokens)
    assert raw_value not in recovered_text, (
        f"{fixture_name}: raw value {raw_value!r} is still recoverable in the output image"
    )
