"""Writes benchmark results to benchmarks/results/ as JSON + CSV, and prints
a P0-priority console summary. Never writes raw sensitive text — rows only
carry types/counts/scores/timings (see runner.BenchmarkRow)."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .metrics import classify_iou
from .runner import BenchmarkRow

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def write_report(
    rows: list[BenchmarkRow], results_dir: str | Path = DEFAULT_RESULTS_DIR, suffix: str = ""
) -> tuple[Path, Path]:
    """`suffix` (e.g. "_hardened") lets a deliberate before/after run avoid
    colliding with a same-day baseline file by name alone. Even without
    one, the timestamp includes hours/minutes/seconds (not just the date) —
    a UTC-vs-local-date mismatch near midnight previously let two runs on
    "different" calendar days collide on the exact same UTC-dated filename
    and silently overwrite an existing baseline; full HHMMSS resolution
    makes that collision astronomically unlikely instead of a real risk.
    """
    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    json_path = results_path / f"ocr_benchmark_{stamp}{suffix}.json"
    csv_path = results_path / f"ocr_benchmark_{stamp}{suffix}.csv"

    for path in (json_path, csv_path):
        if path.exists():
            raise FileExistsError(
                f"refusing to silently overwrite existing benchmark result: {path}. "
                "Pass a distinct `suffix` or wait for the next timestamp."
            )

    payload = [row.to_dict() for row in rows]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if rows:
        fieldnames = list(payload[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(payload)

    return json_path, csv_path


def summarize(rows: list[BenchmarkRow]) -> dict:
    """P0-priority aggregate summary (Skill.md benchmark brief §Security Priority)."""
    if not rows:
        return {}

    total_false_negatives = sum(r.false_negatives for r in rows)
    total_false_positives = sum(r.false_positives for r in rows)
    total_verification_false_pass = sum(1 for r in rows if r.verification_false_pass)

    recalls = [r.recall for r in rows if r.recall is not None]
    ious = [r.mean_iou for r in rows if r.mean_iou is not None]
    precisions = [r.precision for r in rows if r.precision is not None]
    cers = [r.cer for r in rows]
    times = [r.total_time_s for r in rows]
    ocr_times = [r.ocr_time_s for r in rows]
    detect_times = [r.detect_time_s for r in rows]
    redact_verify_times = [r.redact_verify_time_s for r in rows]
    rss_values = [r.rss_after_mb for r in rows if r.rss_after_mb is not None]

    iou_bands: dict[str, int] = {}
    for r in rows:
        band = classify_iou(r.mean_iou)
        iou_bands[band] = iou_bands.get(band, 0) + 1

    verification_pass_count = sum(1 for r in rows if r.verification_status == "PASSED")
    sanity_scan_catch_count = sum(1 for r in rows if r.sanity_scan_triggered)

    return {
        "total_images": len(rows),
        # P0
        "total_false_negatives": total_false_negatives,
        "total_verification_false_pass": total_verification_false_pass,
        "whole_image_sanity_scan_catch_count": sanity_scan_catch_count,
        # P1
        "mean_recall": sum(recalls) / len(recalls) if recalls else None,
        "mean_bbox_iou": sum(ious) / len(ious) if ious else None,
        "iou_bands": iou_bands,
        # P2
        "mean_precision": sum(precisions) / len(precisions) if precisions else None,
        "total_false_positives": total_false_positives,
        "mean_cer": sum(cers) / len(cers) if cers else None,
        # P3
        "mean_total_time_s": sum(times) / len(times) if times else None,
        "mean_ocr_time_s": sum(ocr_times) / len(ocr_times) if ocr_times else None,
        "mean_detect_time_s": sum(detect_times) / len(detect_times) if detect_times else None,
        "mean_redact_verify_time_s": sum(redact_verify_times) / len(redact_verify_times) if redact_verify_times else None,
        # Approximate — see runner._current_rss_mb() docstring: a per-row RSS
        # snapshot, max-reduced here, not a continuously-sampled true peak.
        "approx_peak_rss_mb": max(rss_values) if rss_values else None,
        "verification_pass_rate": verification_pass_count / len(rows) if rows else None,
    }


def print_summary(rows: list[BenchmarkRow]) -> None:
    summary = summarize(rows)
    if not summary:
        print("No benchmark rows to summarize.")
        return

    print(f"\n=== OCR Benchmark Summary ({summary['total_images']} images) ===")
    print(f"[P0] False Negatives (total)          : {summary['total_false_negatives']}")
    print(f"[P0] Verification False PASS (total)   : {summary['total_verification_false_pass']}")
    print(f"[P0] Whole-Image Sanity Scan catches    : {summary['whole_image_sanity_scan_catch_count']}")
    print(f"[P1] Mean Sensitive Detection Recall    : {summary['mean_recall']}")
    print(f"[P1] Mean Bounding Box IoU              : {summary['mean_bbox_iou']}")
    print(f"[P1] IoU quality bands                  : {summary['iou_bands']}")
    print(f"[P2] Mean Precision                     : {summary['mean_precision']}")
    print(f"[P2] False Positives (total)            : {summary['total_false_positives']}")
    print(f"[P2] Mean Character Error Rate           : {summary['mean_cer']}")
    print(f"[P3] Mean total processing time (s)     : {summary['mean_total_time_s']}")
    print(f"     Mean OCR-only time (s)             : {summary['mean_ocr_time_s']}")
    print(f"     Mean Detect+Risk+Policy time (s)   : {summary['mean_detect_time_s']}")
    print(f"     Mean Redact+Verify time (s)        : {summary['mean_redact_verify_time_s']}")
    print(f"     Approx. peak RSS (MB)              : {summary['approx_peak_rss_mb']}")
    print(f"     Verification PASS rate             : {summary['verification_pass_rate']}")
