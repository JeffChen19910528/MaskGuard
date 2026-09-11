"""Upload validation (Phase 8.1 §12). Never trusts the client-declared
Content-Type or filename — every check here is against the ACTUAL bytes,
decoded with Pillow (already a Core dependency; no new decode logic is
invented, this just calls Pillow the same way `preprocessing.py` does).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from .config import ApiSettings
from .errors import FileTooLargeError, ImageDimensionsError, InvalidImageError


@dataclass(frozen=True)
class ValidatedUpload:
    suffix: str  # safe temp-file suffix — never derived from the client's filename (§14)
    width: int
    height: int

#: Pillow format name -> safe suffix for the temp file Core reads from.
#: Deliberately an allowlist (not "whatever Pillow claims to support") —
#: mirrors `cli.py`'s `_IMAGE_SUFFIXES` so the API accepts the same image
#: types the CLI does, nothing broader.
_ALLOWED_FORMATS: dict[str, str] = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "WEBP": ".webp",
    "BMP": ".bmp",
    "TIFF": ".tiff",
}


def validate_upload(data: bytes, settings: ApiSettings) -> ValidatedUpload:
    """Validates raw upload bytes are a real, decodable image within
    configured limits. Returns the safe file suffix to use for the temp
    file (NEVER derived from the client-supplied filename — see §14) and
    the image's real pixel dimensions (Phase 8.3 §13: the review token
    records these so a later manual bbox can be validated without trusting
    anything the client claims about image size).
    Raises an `ApiError` subclass on any failure; never raises a bare
    exception that would surface as an unhandled 500.
    """
    if not data:
        raise InvalidImageError("Uploaded file is empty.")

    if len(data) > settings.max_upload_size_bytes:
        raise FileTooLargeError(
            f"Uploaded file exceeds the {settings.max_upload_size_bytes}-byte limit."
        )

    try:
        image = Image.open(io.BytesIO(data))
        image_format = image.format
    except (UnidentifiedImageError, OSError, ValueError):
        raise InvalidImageError("Uploaded file is not a supported image.") from None

    if image_format not in _ALLOWED_FORMATS:
        raise InvalidImageError(f"Unsupported image format: {image_format!r}.")

    width, height = image.size
    if width <= 0 or height <= 0:
        raise ImageDimensionsError("Image has invalid (zero or negative) dimensions.")
    if width > settings.max_image_width or height > settings.max_image_height:
        raise ImageDimensionsError(
            f"Image dimensions {width}x{height} exceed the "
            f"{settings.max_image_width}x{settings.max_image_height} limit."
        )
    if width * height > settings.max_image_pixels:
        raise ImageDimensionsError(
            f"Image has {width * height} pixels, exceeding the {settings.max_image_pixels}-pixel limit."
        )

    try:
        image.load()  # forces full pixel decode; raises on truncated/corrupt data
    except (OSError, ValueError):
        raise InvalidImageError("Uploaded file could not be decoded — it may be corrupt or truncated.") from None

    return ValidatedUpload(suffix=_ALLOWED_FORMATS[image_format], width=width, height=height)
