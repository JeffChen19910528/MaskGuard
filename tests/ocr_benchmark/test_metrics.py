"""Benchmark framework tests: CER / accuracy / IoU / detection-matching
metrics. No OCR needed — pure function tests against known inputs."""
from benchmarks.ocr.metrics import (
    character_error_rate,
    classify_iou,
    iou,
    levenshtein,
    match_detections,
    text_accuracy,
)


def test_levenshtein_identical_strings_is_zero():
    assert levenshtein("hello", "hello") == 0


def test_levenshtein_known_distance():
    assert levenshtein("kitten", "sitting") == 3


def test_character_error_rate_perfect_match_is_zero():
    assert character_error_rate("A123456789", "A123456789") == 0.0


def test_character_error_rate_empty_reference_with_hypothesis_is_one():
    assert character_error_rate("", "garbage") == 1.0


def test_character_error_rate_empty_reference_and_hypothesis_is_zero():
    assert character_error_rate("", "") == 0.0


def test_text_accuracy_is_complement_of_cer():
    ref, hyp = "A123456789", "A12345678X"
    assert abs(text_accuracy(ref, hyp) - (1 - character_error_rate(ref, hyp))) < 1e-9


def test_iou_identical_boxes_is_one():
    box = (10, 10, 50, 20)
    assert iou(box, box) == 1.0


def test_iou_disjoint_boxes_is_zero():
    assert iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0


def test_iou_partial_overlap_known_value():
    # Two 10x10 boxes overlapping in a 5x10 region: intersection=50, union=150
    box_a = (0, 0, 10, 10)
    box_b = (5, 0, 10, 10)
    assert abs(iou(box_a, box_b) - 50 / 150) < 1e-9


def test_classify_iou_bands():
    assert classify_iou(0.95) == "GOOD"
    assert classify_iou(0.9) == "GOOD"
    assert classify_iou(0.8) == "ACCEPTABLE"
    assert classify_iou(0.7) == "ACCEPTABLE"
    assert classify_iou(0.5) == "NEEDS_REVIEW"
    assert classify_iou(None) == "N/A"


def test_match_detections_true_positive_on_type_and_overlap():
    ground_truth = [{"type": "TaiwanID", "bbox": (100, 100, 50, 20)}]
    detections = [{"type": "TaiwanID", "region": (102, 101, 48, 19)}]
    result = match_detections(ground_truth, detections)
    assert result.true_positives == 1
    assert result.false_negatives == 0
    assert result.false_positives == 0
    assert result.recall == 1.0
    assert result.precision == 1.0


def test_match_detections_false_negative_when_nothing_detected():
    ground_truth = [{"type": "TaiwanID", "bbox": (100, 100, 50, 20)}]
    result = match_detections(ground_truth, [])
    assert result.true_positives == 0
    assert result.false_negatives == 1
    assert result.recall == 0.0
    assert result.precision is None  # undefined: no detections at all


def test_match_detections_false_positive_on_normal_text_image():
    # A "normal, non-sensitive text" image has NO ground truth at all — any
    # reported detection there is a pure false positive.
    result = match_detections([], [{"type": "Email", "region": (0, 0, 10, 10)}])
    assert result.false_positives == 1
    assert result.true_positives == 0
    assert result.precision == 0.0
    assert result.recall is None  # undefined: no ground truth to recall


def test_match_detections_type_mismatch_does_not_count_as_true_positive():
    ground_truth = [{"type": "TaiwanID", "bbox": (100, 100, 50, 20)}]
    detections = [{"type": "Passport", "region": (100, 100, 50, 20)}]  # same box, wrong type
    result = match_detections(ground_truth, detections)
    assert result.true_positives == 0
    assert result.false_negatives == 1
    assert result.false_positives == 1


def test_match_detections_low_iou_below_threshold_does_not_match():
    ground_truth = [{"type": "TaiwanID", "bbox": (0, 0, 10, 10)}]
    detections = [{"type": "TaiwanID", "region": (100, 100, 10, 10)}]  # far away, same type
    result = match_detections(ground_truth, detections, iou_threshold=0.3)
    assert result.true_positives == 0
    assert result.false_negatives == 1
