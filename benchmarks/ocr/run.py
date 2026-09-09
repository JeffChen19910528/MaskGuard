"""CLI entry point: python -m benchmarks.ocr.run [--dataset-dir DIR] [--results-dir DIR]

Generates the synthetic dataset (if not already present), runs it through
every available OCR engine (Tesseract always; PaddleOCR only if installed),
and writes benchmarks/results/ocr_benchmark_<date>.{json,csv}.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from maskguard.config import load_config

from . import dataset as dataset_mod
from .engines import PaddleOcrEngine, TesseractOcrEngine
from .env_check import check_paddleocr_available, check_tesseract_environment
from .report import print_summary, write_report
from .runner import run_benchmark

_GROUND_TRUTH_VALUES = {
    # image -> [{"type", "value"}], used only for the independent
    # Verification-False-PASS re-check; matches benchmarks/ocr/dataset.py's
    # own synthetic values. Kept here (not in ground_truth.json) so this
    # data never round-trips through any file a production log path reads.
    "TaiwanID": [{"type": "TaiwanID", "value": "A123456789"}],
    "Passport": [{"type": "Passport", "value": "PA1234567"}],
    "BankAccount": [{"type": "BankAccount", "value": "1234567890123"}],
    "CreditCard": [{"type": "CreditCard", "value": "4111 1111 1111 1111"}],
    "APIKey": [{"type": "SecretKeyValue", "value": "demo_test_key_123456789"}],
    "Password": [{"type": "SecretKeyValue", "value": "demo_test_pw_123456"}],
}


def _ground_truth_values_by_image(items) -> dict[str, list[dict]]:
    return {item.image: _GROUND_TRUTH_VALUES.get(item.category, []) for item in items}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", default=str(Path(__file__).resolve().parent.parent / "results" / "dataset"))
    parser.add_argument("--results-dir", default=str(Path(__file__).resolve().parent.parent / "results"))
    parser.add_argument("--skip-generate", action="store_true", help="Reuse an existing dataset directory")
    parser.add_argument("--suffix", default="", help="Appended to the output filename, e.g. _hardened")
    args = parser.parse_args()

    tesseract_report = check_tesseract_environment()
    print(f"Tesseract ready: {tesseract_report.ready} ({tesseract_report.missing_summary()})")
    if not tesseract_report.ready:
        print("Tesseract is required for this benchmark run. Aborting.")
        return 1

    if not args.skip_generate:
        print(f"Generating synthetic dataset -> {args.dataset_dir}")
        items = dataset_mod.generate_dataset(args.dataset_dir)
    else:
        items = dataset_mod.load_ground_truth(args.dataset_dir)
    print(f"Dataset: {len(items)} images")

    config = load_config()
    ground_truth_values = _ground_truth_values_by_image(items)

    all_rows = []
    engines = [("Tesseract", TesseractOcrEngine())]

    paddle_available, paddle_reason = check_paddleocr_available()
    if paddle_available:
        engines.append(("PaddleOCR", PaddleOcrEngine()))
    else:
        print(f"PaddleOCR not included in this run: {paddle_reason}")

    for engine_name, engine in engines:
        print(f"\nRunning benchmark for engine: {engine_name}")
        rows = run_benchmark(engine, engine_name, items, args.dataset_dir, config, ground_truth_values)
        all_rows.extend(rows)
        print_summary(rows)

    json_path, csv_path = write_report(all_rows, args.results_dir, suffix=args.suffix)
    print(f"\nWrote {json_path}")
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
