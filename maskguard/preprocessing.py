"""Image Preprocessing (Skill.md §15). Only EXIF-orientation correction is
applied by default, since every later stage (OCR, redaction, output) must
share one coordinate space — any geometric transform run here and not
reflected everywhere else would break bounding-box mapping (§14).

Phase 6.1 P1 adds a lightweight, OCR-only deskew step (`deskew_for_ocr` /
`map_bbox_to_original`). It is deliberately NOT folded into
`load_and_normalize`: the corrected image is only ever handed to the OCR
engine, never used for Redaction or the saved output — Detection/Redaction/
Verification continue to operate on the untouched original image, with OCR
bounding boxes mapped back into its coordinate space first (see
`pipeline.py`). This keeps the "one shared coordinate space" invariant
above intact for every stage except the one call that explicitly maps back.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np
from PIL import Image, ImageOps

from .models import BoundingBox, OcrToken

#: Only correct small skews (Phase 6.1 P1 scope) — a confident angle outside
#: this range is more likely a real rotated/landscape orientation than a
#: scan skew, so it is left alone rather than "corrected" into something worse.
MAX_DESKEW_ANGLE_DEGREES = 10.0
#: Fail-safe floor: too few foreground (dark) pixels to trust an angle
#: estimate at all (e.g. a near-blank image) — leave it untouched.
_MIN_FOREGROUND_PIXELS = 50
#: Skip the warp entirely below this — not worth the resample cost/risk for
#: a rotation this small, and avoids OpenCV's angle-convention edge cases
#: near exactly 0/90 degrees producing pointless "corrections".
_MIN_ANGLE_TO_CORRECT = 0.1


def load_and_normalize(path: str) -> Image.Image:
    image = Image.open(path)
    image = ImageOps.exif_transpose(image)  # bakes EXIF orientation into pixel data
    return image.convert("RGB")


@dataclass
class DeskewResult:
    image: Image.Image  # the input image, or a corrected copy
    angle_degrees: float  # 0.0 if no rotation was applied
    applied: bool


def estimate_skew_angle(image: Image.Image) -> float | None:
    """Lightweight OpenCV skew estimate via `cv2.minAreaRect` over the
    image's foreground (dark) pixels. Returns None whenever the estimate
    isn't trustworthy as a SMALL skew correction — callers must leave the
    image untouched in that case rather than guess."""
    try:
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        coords = cv2.findNonZero(binary)
    except cv2.error:
        return None

    if coords is None or len(coords) < _MIN_FOREGROUND_PIXELS:
        return None

    angle = cv2.minAreaRect(coords)[-1]
    # cv2.minAreaRect's angle is in [-90, 0) (older) or [0, 90) (newer)
    # depending on OpenCV version; normalize to a signed small-angle range.
    if angle < -45:
        angle += 90
    elif angle > 45:
        angle -= 90

    if abs(angle) > MAX_DESKEW_ANGLE_DEGREES:
        return None  # outside the confident small-skew range — fail-safe

    return angle


def deskew_for_ocr(image: Image.Image) -> DeskewResult:
    """Returns a rotation-corrected COPY for OCR only. Never raises — any
    estimation failure or out-of-range angle falls back to returning the
    original image unchanged (`applied=False`), per the fail-safe
    requirement: a wrong guess must never be allowed to damage the image
    actually used for redaction/output."""
    try:
        angle = estimate_skew_angle(image)
    except Exception:
        angle = None

    if angle is None or abs(angle) < _MIN_ANGLE_TO_CORRECT:
        return DeskewResult(image=image, angle_degrees=0.0, applied=False)

    try:
        array = np.array(image.convert("RGB"))
        height, width = array.shape[:2]
        center = (width / 2, height / 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            array, matrix, (width, height), borderValue=(255, 255, 255), flags=cv2.INTER_LINEAR
        )
        return DeskewResult(image=Image.fromarray(rotated), angle_degrees=angle, applied=True)
    except cv2.error:
        return DeskewResult(image=image, angle_degrees=0.0, applied=False)


def map_bbox_to_original(bbox: BoundingBox, image_size: tuple[int, int], angle_degrees: float) -> BoundingBox:
    """Maps a bounding box found in a `deskew_for_ocr`-corrected image back
    to the coordinate space of the ORIGINAL (pre-deskew) image, by applying
    the exact inverse of the rotation matrix `deskew_for_ocr` used. No-op
    when `angle_degrees == 0.0` (deskew was skipped or not applied)."""
    if angle_degrees == 0.0:
        return bbox

    width, height = image_size
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle_degrees, 1.0)
    inverse = cv2.invertAffineTransform(matrix)

    x, y, w, h = bbox.x, bbox.y, bbox.width, bbox.height
    corners = np.array([[x, y], [x + w, y], [x, y + h], [x + w, y + h]], dtype=np.float64)
    homogeneous = np.hstack([corners, np.ones((4, 1))])
    mapped = homogeneous @ inverse.T

    left, top = mapped[:, 0].min(), mapped[:, 1].min()
    right, bottom = mapped[:, 0].max(), mapped[:, 1].max()
    return BoundingBox(x=int(left), y=int(top), width=int(round(right - left)), height=int(round(bottom - top)))


def map_tokens_to_original(tokens: list[OcrToken], image_size: tuple[int, int], angle_degrees: float) -> list[OcrToken]:
    """Applies `map_bbox_to_original` to every token's bounding box — the
    OCR text/confidence/page are unchanged, only the position. No-op list
    comprehension when `angle_degrees == 0.0` (deskew was skipped)."""
    if angle_degrees == 0.0:
        return tokens
    return [
        replace(token, bounding_box=map_bbox_to_original(token.bounding_box, image_size, angle_degrees))
        for token in tokens
    ]
