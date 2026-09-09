"""Regression test for a real incident during Phase 6.1: `write_report`
previously stamped filenames by UTC date only. A benchmark run executed
late at night local time (but still the previous day in UTC) produced the
exact same filename as the prior day's baseline and silently overwrote it.
`write_report` must now refuse to overwrite an existing result file.
"""
import pytest

from benchmarks.ocr.report import write_report
from benchmarks.ocr.runner import BenchmarkRow


def _one_row() -> BenchmarkRow:
    return BenchmarkRow(
        engine="Tesseract", image="x.png", category="TaiwanID", condition="clean",
        ocr_time_s=0.1, detect_time_s=0.01, redact_verify_time_s=0.02, total_time_s=0.13,
        text_accuracy=1.0, cer=0.0, expected_sensitive_count=1, true_positives=1,
        false_negatives=0, false_positives=0, recall=1.0, precision=1.0, mean_iou=0.95,
        verification_status="PASSED", verification_attempts=1, verification_residual_count=0,
        verification_false_pass=False, sanity_scan_triggered=False, sanity_scan_found_types="",
    )


def test_write_report_refuses_to_silently_overwrite_an_existing_file(tmp_path):
    write_report([_one_row()], results_dir=tmp_path, suffix="_test")

    with pytest.raises(FileExistsError):
        write_report([_one_row()], results_dir=tmp_path, suffix="_test")


def test_write_report_with_distinct_suffixes_does_not_collide(tmp_path):
    json_a, csv_a = write_report([_one_row()], results_dir=tmp_path, suffix="_baseline")
    json_b, csv_b = write_report([_one_row()], results_dir=tmp_path, suffix="_hardened")

    assert json_a != json_b
    assert csv_a != csv_b
    assert json_a.exists() and json_b.exists()
