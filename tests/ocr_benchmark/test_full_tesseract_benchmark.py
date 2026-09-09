"""The actual "benchmark test" (Skill.md OCR-benchmark brief): runs the full
51-image synthetic dataset through real Tesseract OCR + the real,
unmodified MaskGuard pipeline stages, writes benchmarks/results/, and
asserts the framework's own measurement capabilities (not a fixed accuracy
bar Tesseract must clear — see the Final Report for what this run found).

Requires the real Tesseract binary + chi_tra language data; SKIPS (not
fails, not passes) when unavailable, exactly like tests/e2e/.
"""
from __future__ import annotations

from maskguard.config import load_config

from benchmarks.ocr.dataset import generate_dataset
from benchmarks.ocr.engines import TesseractOcrEngine
from benchmarks.ocr.metrics import classify_iou
from benchmarks.ocr.report import summarize, write_report
from benchmarks.ocr.runner import run_benchmark

_GROUND_TRUTH_VALUES = {
    "TaiwanID": [{"type": "TaiwanID", "value": "A123456789"}],
    "Passport": [{"type": "Passport", "value": "PA1234567"}],
    "BankAccount": [{"type": "BankAccount", "value": "1234567890123"}],
    "CreditCard": [{"type": "CreditCard", "value": "4111 1111 1111 1111"}],
    "APIKey": [{"type": "SecretKeyValue", "value": "demo_test_key_123456789"}],
    "Password": [{"type": "SecretKeyValue", "value": "demo_test_pw_123456"}],
}


def test_full_benchmark_runs_against_real_tesseract_and_reports_metrics(tesseract_env, tmp_path):
    items = generate_dataset(tmp_path)
    config = load_config()
    ground_truth_values = {item.image: _GROUND_TRUTH_VALUES.get(item.category, []) for item in items}

    rows = run_benchmark(TesseractOcrEngine(), "Tesseract", items, str(tmp_path), config, ground_truth_values)

    assert len(rows) == len(items), "every dataset item must produce exactly one benchmark row"

    # Framework capability assertions (Acceptance Criteria: "可以辨識 False
    # Negative", "可以辨識 Verification False PASS") — these check the
    # MECHANISM works and stays internally consistent, not a fixed accuracy
    # bar (real OCR accuracy varies by image condition; see report.py output
    # and the Final Report for the actual measured numbers this run found).
    for row in rows:
        assert row.false_negatives >= 0
        assert row.false_positives >= 0
        assert isinstance(row.verification_false_pass, bool)
        # Structural invariant: a Verification False PASS can only be real
        # when nothing was actually caught for that image.
        if row.verification_false_pass:
            assert row.true_positives == 0
            assert row.expected_sensitive_count > 0

        # Structural invariant: recall/precision are only defined when
        # their denominator (expected / reported detections) is non-zero.
        if row.expected_sensitive_count == 0:
            assert row.recall is None
        if row.true_positives == 0 and row.false_positives == 0:
            assert row.precision is None

    summary = summarize(rows)
    assert summary["total_images"] == len(items)
    assert summary["total_false_negatives"] == sum(r.false_negatives for r in rows)
    assert summary["total_verification_false_pass"] == sum(1 for r in rows if r.verification_false_pass)

    json_path, csv_path = write_report(rows, tmp_path / "results")
    assert json_path.exists()
    assert csv_path.exists()


def test_iou_quality_bands_are_reported_for_every_matched_detection(tesseract_env, tmp_path):
    items = generate_dataset(tmp_path)
    config = load_config()
    rows = run_benchmark(TesseractOcrEngine(), "Tesseract", items, str(tmp_path), config)

    for row in rows:
        band = classify_iou(row.mean_iou)
        assert band in ("GOOD", "ACCEPTABLE", "NEEDS_REVIEW", "N/A")
        if row.true_positives > 0:
            assert row.mean_iou is not None
