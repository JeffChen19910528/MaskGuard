"""Phase 9.2 EXPERIMENTAL ONLY — single-fixture deep dive on
Passport_clean.png across PSM/OEM/language configurations.

Run: python -m benchmarks.ocr.experiments.passport_boundary_experiment

Reuses `benchmarks.ocr.runner.run_item` UNCHANGED — the exact same
Detection/Risk/Policy/Redaction/Verification/WholeImageSanityScanner
sequence the real 51-image benchmark uses — so every "detected"/
"verification" result below reflects actual production security behavior.
Only the OCR engine's `config=` string and language-list argument vary
between runs. No production file (including
benchmarks/ocr/runner.py itself) is edited or monkey-patched.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from maskguard.config import Config
from maskguard.preprocessing import deskew_for_ocr, load_and_normalize, map_tokens_to_original

from ..dataset import load_ground_truth
from ..runner import run_item
from .configurable_engine import ConfigurableTesseractEngine

DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "results" / "dataset"
IMAGE_PATH = DATASET_DIR / "Passport_clean.png"
EXPECTED_VALUE = "PA1234567"
GROUND_TRUTH_VALUES = [{"type": "Passport", "value": "PA1234567"}]

# --- Configurations to test (§5-7 of the Phase 9.2 spec) -------------------
# "baseline" = production's ACTUAL call (no config= argument at all, i.e.
# pytesseract's own default: PSM 3, OEM = whatever's installed).
PSM_CONFIGS = {
    "baseline_no_override": "",
    "psm3_explicit": "--psm 3",
    "psm6": "--psm 6",
    "psm11": "--psm 11",
    "psm12": "--psm 12",
}
OEM_CONFIGS = {
    "oem_default_(baseline)": "",
    "oem1_lstm_only": "--oem 1",
    "oem3_default_explicit": "--oem 3",
}
LANGUAGE_CONFIGS = {
    "chi_tra+eng_(baseline)": ["zh-TW", "en"],
    "eng_only": ["en"],
    "eng+osd": ["en", "osd"],
    "chi_tra+eng+osd": ["zh-TW", "en", "osd"],
}


def _dump_raw_tokens(tesseract_config: str, languages: list[str]) -> dict:
    """Pure OCR-layer dump (no Detection involved) — what does Tesseract
    itself return under this config, independent of whether any detector
    recognizes it?"""
    engine = ConfigurableTesseractEngine(tesseract_config=tesseract_config)
    image = load_and_normalize(str(IMAGE_PATH))
    deskewed = deskew_for_ocr(image)
    tokens = engine.recognize(deskewed.image, languages)
    tokens = map_tokens_to_original(tokens, deskewed.image.size, deskewed.angle_degrees)
    return {
        "tokens": [
            {"text": t.text, "confidence": round(t.confidence, 3),
             "bbox": {"x": t.bounding_box.x, "y": t.bounding_box.y, "w": t.bounding_box.width, "h": t.bounding_box.height}}
            for t in tokens
        ],
        "recognized_text": " ".join(t.text for t in tokens),
        "exact_value_token_present": any(t.text == EXPECTED_VALUE for t in tokens),
        "deskew_applied": deskewed.applied,
        "deskew_angle_degrees": deskewed.angle_degrees,
    }


def run_one(label: str, tesseract_config: str, languages: list[str]) -> dict:
    engine = ConfigurableTesseractEngine(tesseract_config=tesseract_config)
    config = Config()
    config.ocr.language = languages

    items = load_ground_truth(str(DATASET_DIR))
    item = next(i for i in items if i.image == "Passport_clean.png")

    try:
        raw = _dump_raw_tokens(tesseract_config, languages)
    except Exception as exc:  # noqa: BLE001 - a bad config must not crash the whole sweep
        return {"label": label, "tesseract_config": tesseract_config, "languages": languages, "error": f"OCR call failed: {exc}"}

    t0 = time.perf_counter()
    try:
        row = run_item(engine, "Tesseract-experimental", item, str(IMAGE_PATH), config, GROUND_TRUTH_VALUES)
    except Exception as exc:  # noqa: BLE001
        return {"label": label, "tesseract_config": tesseract_config, "languages": languages, "error": f"pipeline run failed: {exc}", **raw}
    wall_time = time.perf_counter() - t0

    return {
        "label": label,
        "tesseract_config": tesseract_config,
        "languages": languages,
        **raw,
        "recall": row.recall,
        "true_positives": row.true_positives,
        "false_negatives": row.false_negatives,
        "false_positives": row.false_positives,
        "verification_status": row.verification_status,
        "verification_false_pass": row.verification_false_pass,
        "sanity_scan_triggered": row.sanity_scan_triggered,
        "sanity_scan_found_types": row.sanity_scan_found_types,
        "cer": row.cer,
        "ocr_time_s": row.ocr_time_s,
        "wall_time_s": round(wall_time, 4),
    }


def _security_outcome(r: dict) -> str:
    if "error" in r and r.get("error", "").startswith("pipeline"):
        return "UNKNOWN"
    detected = r.get("true_positives", 0) >= 1
    verified_clean_correctly = r.get("verification_status") == "PASSED" and not r.get("verification_false_pass", False)
    if detected and verified_clean_correctly:
        return "SAFE"
    if r.get("verification_false_pass"):
        return "UNSAFE"  # silently passed despite a residual sensitive value
    if not detected and r.get("verification_status") == "FAILED":
        return "SAFE"  # fail-safe: missed at detection, but verification honestly caught it
    return "UNKNOWN"


def _print_row(r: dict) -> None:
    if "error" in r:
        print(f"  [{r['label']:32s}] ERROR: {r['error']}")
        return
    outcome = _security_outcome(r)
    print(
        f"  [{r['label']:32s}] cfg={r['tesseract_config']!r:14s} lang={'+'.join(r['languages']):16s} "
        f"exact_token={str(r['exact_value_token_present']):5s} TP={r['true_positives']} FN={r['false_negatives']} "
        f"verify={r['verification_status']:8s} false_pass={str(r['verification_false_pass']):5s} "
        f"outcome={outcome:7s} text={r['recognized_text'][:50]!r}"
    )


def main() -> int:
    if not IMAGE_PATH.exists():
        print(f"FATAL: fixture not found: {IMAGE_PATH}", file=sys.stderr)
        return 1

    results: dict[str, list[dict]] = {"psm_sweep": [], "oem_sweep": [], "language_sweep": []}

    print("=" * 100)
    print("PSM SWEEP (language=chi_tra+eng baseline, OEM=default)")
    print("=" * 100)
    for label, cfg in PSM_CONFIGS.items():
        r = run_one(label, cfg, ["zh-TW", "en"])
        results["psm_sweep"].append(r)
        r["security_outcome"] = _security_outcome(r)
        _print_row(r)

    print("=" * 100)
    print("OEM SWEEP (language=chi_tra+eng, PSM=baseline/no-override)")
    print("=" * 100)
    for label, oem_cfg in OEM_CONFIGS.items():
        r = run_one(f"{label}__psm_baseline", oem_cfg, ["zh-TW", "en"])
        results["oem_sweep"].append(r)
        r["security_outcome"] = _security_outcome(r)
        _print_row(r)

    print("=" * 100)
    print("OEM SWEEP (language=chi_tra+eng, PSM=6)")
    print("=" * 100)
    for label, oem_cfg in OEM_CONFIGS.items():
        combined = ("--psm 6 " + oem_cfg).strip()
        r = run_one(f"{label}__psm6", combined, ["zh-TW", "en"])
        results["oem_sweep"].append(r)
        r["security_outcome"] = _security_outcome(r)
        _print_row(r)

    print("=" * 100)
    print("LANGUAGE SWEEP (PSM=baseline/no-override, OEM=default)")
    print("=" * 100)
    for label, langs in LANGUAGE_CONFIGS.items():
        r = run_one(label, "", langs)
        results["language_sweep"].append(r)
        r["security_outcome"] = _security_outcome(r)
        _print_row(r)

    out_path = Path(__file__).resolve().parent / "passport_boundary_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
