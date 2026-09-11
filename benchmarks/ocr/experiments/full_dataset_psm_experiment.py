"""Phase 9.2 EXPERIMENTAL ONLY — runs a candidate Tesseract config (found
promising in passport_boundary_experiment.py) against the COMPLETE,
UNMODIFIED existing 51-image benchmark dataset, via the real, unmodified
`benchmarks.ocr.runner.run_benchmark` (same code the actual benchmark CLI
uses) — never a subset, never a new/replacement dataset.

Run: python -m benchmarks.ocr.experiments.full_dataset_psm_experiment

No production file is edited. `maskguard/ocr/tesseract_engine.py` is never
imported or modified by this script — only `ConfigurableTesseractEngine`
(this experiments package) is used, with an explicit `config=` string.
"""
from __future__ import annotations

import json
from pathlib import Path

from maskguard.config import Config

from ..dataset import load_ground_truth
from ..run import _ground_truth_values_by_image
from ..runner import run_benchmark
from .configurable_engine import ConfigurableTesseractEngine

DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "results" / "dataset"

# Candidates found in the single-fixture PSM/OEM/language sweep
# (passport_boundary_results.json): PSM 6 (with default OEM) fixed the
# Passport_clean.png finding cleanly. Testing PSM 6 alone (OEM untouched,
# matching baseline) here — the OEM sweep at PSM 6 showed no OEM-dependent
# difference, so OEM is held at production default throughout.
CANDIDATES = {
    "production_baseline_(no_override)": "",
    "psm6_candidate": "--psm 6",
}


def summarize(rows) -> dict:
    n = len(rows)
    if n == 0:
        return {}
    total_fn = sum(r.false_negatives for r in rows)
    total_fp = sum(r.false_positives for r in rows)
    total_false_pass = sum(1 for r in rows if r.verification_false_pass)
    mean_recall = sum(r.recall for r in rows if r.recall is not None) / n
    ious = [r.mean_iou for r in rows if r.mean_iou is not None]
    mean_iou = sum(ious) / len(ious) if ious else None
    mean_cer = sum(r.cer for r in rows if r.cer is not None) / n
    mean_ocr_time = sum(r.ocr_time_s for r in rows) / n
    mean_total_time = sum(r.total_time_s for r in rows) / n
    return {
        "n_images": n,
        "mean_recall": mean_recall,
        "false_negatives_total": total_fn,
        "false_positives_total": total_fp,
        "verification_false_pass_total": total_false_pass,
        "mean_iou": mean_iou,
        "mean_cer": mean_cer,
        "mean_ocr_time_s": mean_ocr_time,
        "mean_total_time_s": mean_total_time,
    }


def per_category_condition_deltas(baseline_rows, candidate_rows) -> list[dict]:
    """Row-by-row diff — flags any (category, condition) where the
    candidate's recall/FN/false-pass got WORSE than baseline, so a
    dataset-wide average improvement can never silently hide a per-fixture
    regression (Phase 9.2 §14 security gate, §15/§16)."""
    baseline_by_key = {(r.category, r.condition): r for r in baseline_rows}
    regressions = []
    for cand in candidate_rows:
        key = (cand.category, cand.condition)
        base = baseline_by_key.get(key)
        if base is None:
            continue
        recall_regressed = cand.recall is not None and base.recall is not None and cand.recall < base.recall
        fn_regressed = cand.false_negatives > base.false_negatives
        fp_regressed = cand.false_positives > base.false_positives
        false_pass_regressed = cand.verification_false_pass and not base.verification_false_pass
        if recall_regressed or fn_regressed or fp_regressed or false_pass_regressed:
            regressions.append({
                "category": cand.category,
                "condition": cand.condition,
                "baseline_recall": base.recall, "candidate_recall": cand.recall,
                "baseline_fn": base.false_negatives, "candidate_fn": cand.false_negatives,
                "baseline_fp": base.false_positives, "candidate_fp": cand.false_positives,
                "baseline_false_pass": base.verification_false_pass, "candidate_false_pass": cand.verification_false_pass,
            })
    return regressions


def main() -> int:
    items = load_ground_truth(str(DATASET_DIR))
    gt_by_image = _ground_truth_values_by_image(items)

    all_results = {}
    all_rows = {}
    for label, tesseract_config in CANDIDATES.items():
        print(f"=== Running full 51-image dataset with config={tesseract_config!r} ({label}) ===")
        engine = ConfigurableTesseractEngine(tesseract_config=tesseract_config)
        config = Config()
        rows = run_benchmark(engine, f"Tesseract-{label}", items, str(DATASET_DIR), config, gt_by_image)
        all_rows[label] = rows
        summary = summarize(rows)
        all_results[label] = summary
        print(json.dumps(summary, indent=2))

    baseline_label = "production_baseline_(no_override)"
    print("\n=== Per-fixture regression check (candidate vs baseline) ===")
    for label, rows in all_rows.items():
        if label == baseline_label:
            continue
        regressions = per_category_condition_deltas(all_rows[baseline_label], rows)
        print(f"\n--- {label}: {len(regressions)} fixture(s) regressed vs baseline ---")
        for reg in regressions:
            print(f"  {reg['category']}/{reg['condition']}: "
                  f"recall {reg['baseline_recall']}->{reg['candidate_recall']}, "
                  f"FN {reg['baseline_fn']}->{reg['candidate_fn']}, "
                  f"FP {reg['baseline_fp']}->{reg['candidate_fp']}, "
                  f"false_pass {reg['baseline_false_pass']}->{reg['candidate_false_pass']}")

    out_path = Path(__file__).resolve().parent / "full_dataset_psm_results.json"
    serializable = {
        label: {
            "summary": all_results[label],
            "rows": [
                {
                    "category": r.category, "condition": r.condition,
                    "recall": r.recall, "false_negatives": r.false_negatives,
                    "false_positives": r.false_positives, "mean_iou": r.mean_iou,
                    "cer": r.cer, "verification_status": r.verification_status,
                    "verification_false_pass": r.verification_false_pass,
                    "ocr_time_s": r.ocr_time_s, "total_time_s": r.total_time_s,
                }
                for r in all_rows[label]
            ],
        }
        for label in CANDIDATES
    }
    out_path.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
