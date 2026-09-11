"""Phase 7: builds a Tesseract-vs-PaddleOCR comparison from two already-run
benchmark result files (produced by `python -m benchmarks.ocr.run`, one per
engine, against the SAME dataset/ground-truth — see the Phase 7 report for
why each engine is run separately, from its own environment/venv).

This module only reads/aggregates existing `BenchmarkRow` JSON output — it
never re-runs OCR, never touches Detection/Risk/Policy/Redaction/
Verification, and never changes how `match_detections`/`summarize` define a
metric (Phase 7 brief §2/§10: comparison, not tuning).
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

_MAJOR_TYPES = [
    "TaiwanID", "Passport", "BankAccount", "CreditCard", "Email",
    "PhoneTW", "APIKey", "Password", "Address",
]

_CONDITIONS = ["clean", "low_res", "blurred", "rotated", "font_large"]

_EXTRA_ROW_CATEGORIES = {
    # "chinese_labeled_field" ("姓名：王小明") is the only Traditional-Chinese
    # / mixed-language dataset category that carries a sensitive-detection
    # ground truth (a PersonalName region) — "traditional_chinese_text" and
    # "mixed_chinese_english" are pure OCR-accuracy categories with NO
    # sensitive ground truth at all (dataset.py's _LANGUAGE_VARIETY_LINES),
    # so `recall` is structurally undefined (0/0) for them; `_condition_row`
    # below reports CER/text-accuracy for those instead of a fabricated
    # recall number.
    "Traditional Chinese (labeled field)": "chinese_labeled_field",
    "Traditional Chinese (plain text, OCR-only)": "traditional_chinese_text",
    "Mixed Language (plain text, OCR-only)": "mixed_chinese_english",
}


def _load_rows(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _overall_summary(rows: list[dict]) -> dict:
    recalls = [r["recall"] for r in rows if r.get("recall") is not None]
    ious = [r["mean_iou"] for r in rows if r.get("mean_iou") is not None]
    precisions = [r["precision"] for r in rows if r.get("precision") is not None]
    rss = [r["rss_after_mb"] for r in rows if r.get("rss_after_mb") is not None]
    return {
        "images": len(rows),
        "mean_recall": _mean(recalls),
        "total_false_negatives": sum(r["false_negatives"] for r in rows),
        "total_verification_false_pass": sum(1 for r in rows if r.get("verification_false_pass")),
        "total_false_positives": sum(r["false_positives"] for r in rows),
        "mean_precision": _mean(precisions),
        "mean_iou": _mean(ious),
        "mean_cer": _mean([r["cer"] for r in rows]),
        "mean_text_accuracy": _mean([r["text_accuracy"] for r in rows]),
        "mean_ocr_time_s": _mean([r["ocr_time_s"] for r in rows]),
        "mean_total_time_s": _mean([r["total_time_s"] for r in rows]),
        "approx_peak_rss_mb": max(rss) if rss else None,
    }


def _recall_by_type(rows: list[dict]) -> dict[str, float | None]:
    return {t: _mean([r["recall"] for r in rows if r["category"] == t]) for t in _MAJOR_TYPES}


def _row_metrics(rows: list[dict]) -> dict[str, float | None]:
    return {
        "recall": _mean([r["recall"] for r in rows]),
        "cer": _mean([r["cer"] for r in rows]),
        "text_accuracy": _mean([r["text_accuracy"] for r in rows]),
    }


def _recall_by_condition(rows: list[dict]) -> dict[str, dict[str, float | None]]:
    major_rows = [r for r in rows if r["category"] in _MAJOR_TYPES]
    by_condition = {
        cond: _row_metrics([r for r in major_rows if r["condition"] == cond]) for cond in _CONDITIONS
    }
    for label, category in _EXTRA_ROW_CATEGORIES.items():
        by_condition[label] = _row_metrics([r for r in rows if r["category"] == category])
    return by_condition


def _cold_vs_warm(rows: list[dict]) -> dict:
    """First row processed = cold start (pays model init/load); the rest are
    warm-run. Only meaningful within a single engine's own run ordering."""
    if not rows:
        return {"cold_start_ocr_time_s": None, "warm_mean_ocr_time_s": None}
    return {
        "cold_start_ocr_time_s": rows[0]["ocr_time_s"],
        "warm_mean_ocr_time_s": _mean([r["ocr_time_s"] for r in rows[1:]]),
    }


def build_comparison(tesseract_rows: list[dict], paddle_rows: list[dict]) -> dict:
    return {
        "tesseract": {
            "overall": _overall_summary(tesseract_rows),
            "recall_by_type": _recall_by_type(tesseract_rows),
            "recall_by_condition": _recall_by_condition(tesseract_rows),
            "cold_vs_warm": _cold_vs_warm(tesseract_rows),
        },
        "paddleocr": {
            "overall": _overall_summary(paddle_rows),
            "recall_by_type": _recall_by_type(paddle_rows),
            "recall_by_condition": _recall_by_condition(paddle_rows),
            "cold_vs_warm": _cold_vs_warm(paddle_rows),
        },
    }


def _flatten_for_csv(comparison: dict) -> list[dict]:
    rows = []
    for section in ("overall", "recall_by_type", "recall_by_condition", "cold_vs_warm"):
        t_section = comparison["tesseract"][section]
        p_section = comparison["paddleocr"][section]
        keys = set(t_section) | set(p_section)
        for key in sorted(keys):
            t_val, p_val = t_section.get(key), p_section.get(key)
            if isinstance(t_val, dict) or isinstance(p_val, dict):
                sub_keys = set((t_val or {})) | set((p_val or {}))
                for sub_key in sorted(sub_keys):
                    rows.append(
                        {
                            "section": section,
                            "metric": f"{key}.{sub_key}",
                            "tesseract": (t_val or {}).get(sub_key),
                            "paddleocr": (p_val or {}).get(sub_key),
                        }
                    )
            else:
                rows.append({"section": section, "metric": key, "tesseract": t_val, "paddleocr": p_val})
    return rows


def write_comparison(
    tesseract_path: str | Path, paddle_path: str | Path, results_dir: str | Path = DEFAULT_RESULTS_DIR
) -> tuple[Path, Path]:
    comparison = build_comparison(_load_rows(tesseract_path), _load_rows(paddle_path))

    results_path = Path(results_dir)
    results_path.mkdir(parents=True, exist_ok=True)
    json_path = results_path / "ocr_benchmark_phase7_comparison.json"
    csv_path = results_path / "ocr_benchmark_phase7_comparison.csv"

    json_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")

    flat_rows = _flatten_for_csv(comparison)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["section", "metric", "tesseract", "paddleocr"])
        writer.writeheader()
        writer.writerows(flat_rows)

    return json_path, csv_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tesseract-json", required=True)
    parser.add_argument("--paddle-json", required=True)
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()

    json_path, csv_path = write_comparison(args.tesseract_json, args.paddle_json, args.results_dir)
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
