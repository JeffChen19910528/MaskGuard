"""Benchmark metrics. Security-priority order (per the benchmark brief):

P0: False Negative count, Verification False PASS count
P1: Sensitive Detection Recall, Bounding Box correctness (IoU)
P2: Precision, Character Error Rate
P3: Processing time

None of this feeds back into production risk/policy thresholds — the IoU
quality bands here are a benchmark-reporting parameter only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

IOU_GOOD_THRESHOLD = 0.9
IOU_ACCEPTABLE_THRESHOLD = 0.7


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current_row = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current_row.append(
                min(
                    previous_row[j] + 1,  # deletion
                    current_row[j - 1] + 1,  # insertion
                    previous_row[j - 1] + cost,  # substitution
                )
            )
        previous_row = current_row
    return previous_row[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """CER = edit_distance(reference, hypothesis) / len(reference)."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein(reference, hypothesis) / len(reference)


def text_accuracy(reference: str, hypothesis: str) -> float:
    return max(0.0, 1.0 - character_error_rate(reference, hypothesis))


Rect = tuple[int, int, int, int]  # x, y, width, height


def _as_corners(rect: Rect) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    return x, y, x + w, y + h


def iou(box_a: Rect, box_b: Rect) -> float:
    ax0, ay0, ax1, ay1 = _as_corners(box_a)
    bx0, by0, bx1, by1 = _as_corners(box_b)

    inter_left, inter_top = max(ax0, bx0), max(ay0, by0)
    inter_right, inter_bottom = min(ax1, bx1), min(ay1, by1)
    if inter_right <= inter_left or inter_bottom <= inter_top:
        return 0.0

    inter_area = (inter_right - inter_left) * (inter_bottom - inter_top)
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0


def classify_iou(value: float | None) -> str:
    if value is None:
        return "N/A"
    if value >= IOU_GOOD_THRESHOLD:
        return "GOOD"
    if value >= IOU_ACCEPTABLE_THRESHOLD:
        return "ACCEPTABLE"
    return "NEEDS_REVIEW"


@dataclass
class DetectionMatch:
    """Result of matching ground-truth sensitive regions against a set of
    reported detections (type + region) for one image."""

    true_positives: int = 0
    false_negatives: int = 0
    false_positives: int = 0
    matched_ious: list[float] = field(default_factory=list)

    @property
    def recall(self) -> float | None:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else None

    @property
    def precision(self) -> float | None:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else None

    @property
    def mean_iou(self) -> float | None:
        return sum(self.matched_ious) / len(self.matched_ious) if self.matched_ious else None


def match_detections(
    ground_truth: list[dict],  # [{"type": str, "bbox": Rect}, ...]
    detections: list[dict],  # [{"type": str, "region": Rect}, ...]
    iou_threshold: float = 0.3,
) -> DetectionMatch:
    """Greedy best-IoU matching per ground-truth region, same type required.
    `iou_threshold` here is a lenient MATCHING threshold (is this even the
    same physical region at all?) — separate from the quality bands in
    `classify_iou` (is the match a GOOD/ACCEPTABLE/NEEDS_REVIEW box fit?).
    """
    used_detection_indices: set[int] = set()
    matched_ious: list[float] = []
    true_positives = 0

    for gt in ground_truth:
        best_idx, best_iou = None, 0.0
        for idx, det in enumerate(detections):
            if idx in used_detection_indices or det["type"] != gt["type"]:
                continue
            score = iou(det["region"], gt["bbox"])
            if score > best_iou:
                best_idx, best_iou = idx, score
        if best_idx is not None and best_iou >= iou_threshold:
            used_detection_indices.add(best_idx)
            matched_ious.append(best_iou)
            true_positives += 1

    false_negatives = len(ground_truth) - true_positives
    false_positives = len(detections) - len(used_detection_indices)
    return DetectionMatch(true_positives, false_negatives, false_positives, matched_ious)
