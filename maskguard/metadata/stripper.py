"""Metadata Protection (Skill.md §23): strip EXIF/GPS/camera/author/thumbnail
data from the output image by default (`preserve_metadata = false`)."""
from __future__ import annotations

from PIL import Image


def strip_metadata(image: Image.Image) -> Image.Image:
    """Return a copy with no EXIF/ICC/XMP metadata, pixel data unchanged.

    `Image.paste` copies pixel data only, not the `.info` dict (EXIF, ICC
    profile, etc.), so the new image starts with a clean slate.
    """
    clean = Image.new(image.mode, image.size)
    clean.paste(image, (0, 0))
    return clean
