"""Redaction primitives (Skill.md §13): solid mask, blur, pixelation, partial mask."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from ..models import BoundingBox


def _padded_rect(box: BoundingBox, padding: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = box.as_rect()
    return left - padding, top - padding, right + padding, bottom + padding


def solid_mask(image: Image.Image, box: BoundingBox, padding: int = 2, color=(0, 0, 0)) -> None:
    """§13.1 — full opaque cover. Used for Password/Token/API Key/ID/CreditCard."""
    draw = ImageDraw.Draw(image)
    draw.rectangle(_padded_rect(box, padding), fill=color)


def blur(image: Image.Image, box: BoundingBox, padding: int = 2, radius: float = 12.0) -> None:
    """§13.2 — Gaussian blur, configurable radius."""
    rect = _padded_rect(box, padding)
    rect = (max(rect[0], 0), max(rect[1], 0), min(rect[2], image.width), min(rect[3], image.height))
    if rect[2] <= rect[0] or rect[3] <= rect[1]:
        return
    region = image.crop(rect).filter(ImageFilter.GaussianBlur(radius))
    image.paste(region, rect)


def pixelate(image: Image.Image, box: BoundingBox, padding: int = 2, block_size: int = 8) -> None:
    """§13.3 — shrink then enlarge to create a mosaic effect."""
    rect = _padded_rect(box, padding)
    rect = (max(rect[0], 0), max(rect[1], 0), min(rect[2], image.width), min(rect[3], image.height))
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    if width <= 0 or height <= 0:
        return
    region = image.crop(rect)
    small_w = max(1, width // block_size)
    small_h = max(1, height // block_size)
    region = region.resize((small_w, small_h), Image.NEAREST).resize((width, height), Image.NEAREST)
    image.paste(region, rect)


def partial_mask(image: Image.Image, box: BoundingBox, padding: int = 2, keep_ratio: float = 0.2) -> None:
    """§13.4 — cover the middle of the region, leaving edges visible
    (approximates "0912****78" / "john****@gmail.com" text-level partial masks)."""
    left, top, right, bottom = _padded_rect(box, padding)
    width = right - left
    keep_width = max(1, int(width * keep_ratio))
    mask_left = left + keep_width
    mask_right = right - keep_width
    if mask_right <= mask_left:
        solid_mask(image, box, padding)
        return
    draw = ImageDraw.Draw(image)
    draw.rectangle((mask_left, top, mask_right, bottom), fill=(0, 0, 0))
