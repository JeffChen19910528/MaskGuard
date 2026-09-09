"""Phase 6.1 P1 regression tests: lightweight OpenCV-based deskew +
bounding-box coordinate mapping back to the original image space.
"""
import numpy as np
from PIL import Image

from maskguard.models import BoundingBox
from maskguard.preprocessing import (
    MAX_DESKEW_ANGLE_DEGREES,
    DeskewResult,
    deskew_for_ocr,
    estimate_skew_angle,
    map_bbox_to_original,
)


def _skewed_text_line_image(angle_degrees: float, size=(400, 150)) -> Image.Image:
    """A synthetic "text line" (solid black bar) rotated by `angle_degrees`,
    standing in for a slightly-skewed scanned document line."""
    import cv2

    base = Image.new("RGB", size, (255, 255, 255))
    arr = np.array(base)
    cv2.rectangle(arr, (50, 60), (350, 90), (0, 0, 0), -1)
    base = Image.fromarray(arr)
    return base.rotate(-angle_degrees, expand=False, fillcolor=(255, 255, 255))


def _bbox_of_dark_pixels(image: Image.Image) -> BoundingBox:
    arr = np.array(image.convert("L"))
    ys, xs = np.where(arr < 128)
    return BoundingBox(x=int(xs.min()), y=int(ys.min()), width=int(xs.max() - xs.min()), height=int(ys.max() - ys.min()))


# ---------------------------------------------------------------------------
# 1: OCR Recall improvement precondition — angle estimation must correctly
# recover a known small skew angle.
# ---------------------------------------------------------------------------


def test_estimate_skew_angle_recovers_known_six_degree_skew():
    image = _skewed_text_line_image(6.0)
    angle = estimate_skew_angle(image)
    assert angle is not None
    assert abs(angle - 6.0) < 1.0


def test_estimate_skew_angle_recovers_negative_skew():
    image = _skewed_text_line_image(-6.0)
    angle = estimate_skew_angle(image)
    assert angle is not None
    assert abs(angle + 6.0) < 1.0


def test_deskew_for_ocr_straightens_a_skewed_line():
    image = _skewed_text_line_image(6.0)
    result = deskew_for_ocr(image)
    assert result.applied is True
    assert abs(result.angle_degrees - 6.0) < 1.0

    # The corrected image's dark-pixel bbox height should shrink back close
    # to the original unrotated bar's height (30px) — a skewed bar's
    # axis-aligned bbox is taller than the bar itself.
    corrected_bbox = _bbox_of_dark_pixels(result.image)
    assert corrected_bbox.height < 40  # ~30px bar, some antialiasing slack


# ---------------------------------------------------------------------------
# Fail-safe requirements: never guess on an unreliable or out-of-range angle.
# ---------------------------------------------------------------------------


def test_deskew_skips_correction_on_a_blank_image():
    blank = Image.new("RGB", (200, 100), (255, 255, 255))
    result = deskew_for_ocr(blank)
    assert result.applied is False
    assert result.angle_degrees == 0.0
    assert result.image is blank  # original object returned unchanged, not a copy


def test_estimate_skew_angle_returns_none_for_blank_image():
    blank = Image.new("RGB", (200, 100), (255, 255, 255))
    assert estimate_skew_angle(blank) is None


def test_deskew_does_not_correct_a_large_rotation_outside_confident_range():
    # A genuine ~45-degree rotation is far outside "small scan skew"
    # territory (Skill.md §14/§40 fail-safe: don't guess) — must be left
    # alone rather than "corrected" into something worse.
    image = _skewed_text_line_image(45.0)
    angle = estimate_skew_angle(image)
    assert angle is None or abs(angle) <= MAX_DESKEW_ANGLE_DEGREES

    result = deskew_for_ocr(image)
    if angle is None:
        assert result.applied is False


def test_deskew_never_raises_on_pathological_input():
    # 1x1 image: not enough foreground pixels for any reliable estimate.
    tiny = Image.new("RGB", (1, 1), (255, 255, 255))
    result = deskew_for_ocr(tiny)
    assert isinstance(result, DeskewResult)
    assert result.applied is False


# ---------------------------------------------------------------------------
# 2 & 3: Bounding box mapping back to ORIGINAL image coordinates.
# ---------------------------------------------------------------------------


def test_map_bbox_to_original_recovers_the_correct_region():
    skewed = _skewed_text_line_image(6.0)
    result = deskew_for_ocr(skewed)
    assert result.applied is True

    bbox_in_corrected_image = _bbox_of_dark_pixels(result.image)
    mapped_back = map_bbox_to_original(bbox_in_corrected_image, result.image.size, result.angle_degrees)

    actual_bbox_in_original = _bbox_of_dark_pixels(skewed)

    # Allow a few pixels of rounding/antialiasing slack, not an exact match.
    assert abs(mapped_back.x - actual_bbox_in_original.x) <= 4
    assert abs(mapped_back.y - actual_bbox_in_original.y) <= 4
    assert abs((mapped_back.x + mapped_back.width) - (actual_bbox_in_original.x + actual_bbox_in_original.width)) <= 4
    assert abs((mapped_back.y + mapped_back.height) - (actual_bbox_in_original.y + actual_bbox_in_original.height)) <= 4


def test_map_bbox_to_original_is_a_no_op_when_angle_is_zero():
    bbox = BoundingBox(x=10, y=20, width=30, height=40)
    mapped = map_bbox_to_original(bbox, (200, 100), 0.0)
    assert mapped == bbox
