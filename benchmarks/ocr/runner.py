"""Benchmark runner: Image -> (real, unmodified) MaskGuard pipeline stages,
timed and scored against ground truth, for one OCR engine at a time.

Every stage below is the actual production class from `maskguard.*` — this
module only adds timing and metric computation around them. No production
file is imported for its *side effects*; nothing here monkey-patches or
subclasses production code.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from maskguard.config import Config
from maskguard.detection import ContextDetector, KeywordDetector, RegexDetector
from maskguard.ocr.base import IOcrEngine
from maskguard.policy import PolicyEngine
from maskguard.preprocessing import deskew_for_ocr, load_and_normalize, map_tokens_to_original
from maskguard.redaction import RedactionEngine
from maskguard.risk import RiskEngine
from maskguard.verification import VerificationEngine, WholeImageSanityScanner, apply_sanity_scan

from .dataset import DatasetItem
from .metrics import DetectionMatch, character_error_rate, match_detections, text_accuracy


@dataclass
class BenchmarkRow:
    engine: str
    image: str
    category: str
    condition: str

    ocr_time_s: float
    detect_time_s: float
    redact_verify_time_s: float
    total_time_s: float

    text_accuracy: float
    cer: float

    expected_sensitive_count: int
    true_positives: int
    false_negatives: int
    false_positives: int
    recall: float | None
    precision: float | None
    mean_iou: float | None

    verification_status: str
    verification_attempts: int
    verification_residual_count: int
    verification_false_pass: bool  # independent re-check, see runner.py docstring below
    sanity_scan_triggered: bool  # Phase 6.1 P0-2: did the whole-image sanity scan find anything?
    sanity_scan_found_types: str  # comma-joined type names, "" if clean (kept scalar for the CSV column)

    def to_dict(self) -> dict:
        return asdict(self)


def _independent_false_pass_check(
    ocr_engine: IOcrEngine, redacted_image, ground_truth: list[dict], languages: list[str]
) -> bool:
    """Second-opinion leak check, decoupled from VerificationEngine's own
    verdict: re-OCR the WHOLE final image (not just the box VerificationEngine
    itself decided to check) and see whether any ground-truth sensitive value
    the item is supposed to have removed is still recoverable anywhere in it.
    Only meaningful for images the pipeline reported as PASSED — if this
    finds a leak anyway, that IS a Verification False PASS.
    """
    if not ground_truth:
        return False
    tokens = ocr_engine.recognize(redacted_image, languages)
    recovered = " ".join(t.text for t in tokens)
    from maskguard.verification.normalization import normalize_for_verification

    normalized_recovered = normalize_for_verification(recovered)
    for region in ground_truth:
        needle = normalize_for_verification(region.get("value", ""), region["type"])
        if needle and needle in normalized_recovered:
            return True
    return False


def run_item(
    engine: IOcrEngine,
    engine_name: str,
    item: DatasetItem,
    image_path: str,
    config: Config,
    ground_truth_values: list[dict] | None = None,
) -> BenchmarkRow:
    """`ground_truth_values` (optional) is [{"type", "value"}] used ONLY for
    the independent False-PASS re-check above — it never reaches any
    production log, only this benchmark's in-memory comparison.
    """
    image = load_and_normalize(image_path)

    # Phase 6.1 P1: same deskew step Pipeline.process() applies — OCR sees a
    # deskewed copy, tokens are mapped back to `image`'s own coordinates
    # immediately after, so ground-truth comparison below stays correct.
    t0 = time.perf_counter()
    deskewed = deskew_for_ocr(image)
    tokens = engine.recognize(deskewed.image, config.ocr.language)
    tokens = map_tokens_to_original(tokens, deskewed.image.size, deskewed.angle_degrees)
    ocr_time = time.perf_counter() - t0
    recognized_text = " ".join(t.text for t in tokens)

    t1 = time.perf_counter()
    detections = RegexDetector().detect(tokens) + ContextDetector().detect(tokens)
    keyword_hits = KeywordDetector().detect(tokens)
    scored = RiskEngine().score(detections, keyword_hits)
    decided = PolicyEngine(config.masking).decide(scored)
    detect_time = time.perf_counter() - t1

    ground_truth_regions = [{"type": s.type, "bbox": s.bbox} for s in item.sensitive]
    reported_detections = [
        {"type": d.type, "region": (d.bounding_box.x, d.bounding_box.y, d.bounding_box.width, d.bounding_box.height)}
        for d in decided
    ]
    match: DetectionMatch = match_detections(ground_truth_regions, reported_detections)

    t2 = time.perf_counter()
    verification_engine = VerificationEngine(engine, RedactionEngine(), max_retries=config.masking.max_verification_retries)
    redacted, verification = verification_engine.verify_and_fix(image, decided, config.ocr.language)

    # Phase 6.1 P0-2: the same independent safety net Pipeline.process() now
    # runs, applied here too so the benchmark measures the HARDENED
    # behavior, not the pre-Phase-6.1 VerificationEngine-only verdict.
    # (Also deskewed, matching Pipeline.process()'s P1 wiring.)
    scan_result = WholeImageSanityScanner(engine).scan(deskew_for_ocr(redacted).image, config.ocr.language)
    verification = apply_sanity_scan(verification, scan_result)
    redact_verify_time = time.perf_counter() - t2

    false_pass = False
    if verification.status == "PASSED" and ground_truth_values:
        false_pass = _independent_false_pass_check(engine, redacted, ground_truth_values, config.ocr.language)

    return BenchmarkRow(
        engine=engine_name,
        image=item.image,
        category=item.category,
        condition=item.condition,
        ocr_time_s=ocr_time,
        detect_time_s=detect_time,
        redact_verify_time_s=redact_verify_time,
        total_time_s=ocr_time + detect_time + redact_verify_time,
        text_accuracy=text_accuracy(item.text, recognized_text),
        cer=character_error_rate(item.text, recognized_text),
        expected_sensitive_count=len(item.sensitive),
        true_positives=match.true_positives,
        false_negatives=match.false_negatives,
        false_positives=match.false_positives,
        recall=match.recall,
        precision=match.precision,
        mean_iou=match.mean_iou,
        verification_status=verification.status,
        verification_attempts=verification.attempts,
        verification_residual_count=verification.residual_count,
        verification_false_pass=false_pass,
        sanity_scan_triggered=not scan_result.clean,
        sanity_scan_found_types=",".join(scan_result.found_types),
    )


def run_benchmark(
    engine: IOcrEngine,
    engine_name: str,
    dataset_items: list[DatasetItem],
    dataset_dir: str,
    config: Config,
    ground_truth_values_by_image: dict[str, list[dict]] | None = None,
) -> list[BenchmarkRow]:
    from pathlib import Path

    rows = []
    for item in dataset_items:
        image_path = str(Path(dataset_dir) / item.image)
        gt_values = (ground_truth_values_by_image or {}).get(item.image)
        rows.append(run_item(engine, engine_name, item, image_path, config, gt_values))
    return rows
