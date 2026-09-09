"""Image Preprocessing (Skill.md §15). Only EXIF-orientation correction is
applied by default, since every later stage (OCR, redaction, output) must
share one coordinate space — any geometric transform run here and not
reflected everywhere else would break bounding-box mapping (§14)."""
from __future__ import annotations

from PIL import Image, ImageOps


def load_and_normalize(path: str) -> Image.Image:
    image = Image.open(path)
    image = ImageOps.exif_transpose(image)  # bakes EXIF orientation into pixel data
    return image.convert("RGB")
