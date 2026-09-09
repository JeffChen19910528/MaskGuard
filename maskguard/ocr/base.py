"""OCR engine interface. Skill.md §9: multi-engine, replaceable, never bound to one provider."""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL.Image import Image

from ..models import OcrToken


class IOcrEngine(ABC):
    """Every implementation must return text + confidence + bounding box, never text alone."""

    #: True if this engine sends image data outside the local machine.
    is_cloud: bool = False

    @abstractmethod
    def recognize(self, image: Image, languages: list[str]) -> list[OcrToken]:
        """Run OCR on a single image and return positioned tokens."""
        raise NotImplementedError
