"""Redaction Engine (Skill.md §13, §29). Executes whatever action the Policy
Engine assigned; also implements the escalation ladder used by the
Verification Engine when residual sensitive data is detected (§16)."""
from __future__ import annotations

from PIL import Image

from ..models import BoundingBox, Detection, RedactionAction
from . import methods


class RedactionEngine:
    def apply(self, image: Image.Image, detections: list[Detection]) -> Image.Image:
        output = image.copy()
        for detection in detections:
            self._apply_one(output, detection)
        return output

    def _apply_one(self, image: Image.Image, detection: Detection) -> None:
        box = detection.bounding_box
        if detection.action == RedactionAction.FULL_MASK:
            methods.solid_mask(image, box)
        elif detection.action == RedactionAction.BLUR:
            methods.blur(image, box)
        elif detection.action == RedactionAction.PIXELATE:
            methods.pixelate(image, box)
        elif detection.action == RedactionAction.PARTIAL_MASK:
            methods.partial_mask(image, box)

    def escalate(self, detection: Detection) -> None:
        """§16 verification-failure ladder: widen the box, then switch to a
        stronger method, finally falling back to a full solid mask."""
        if detection.action == RedactionAction.PARTIAL_MASK:
            detection.action = RedactionAction.BLUR
        elif detection.action == RedactionAction.BLUR:
            detection.action = RedactionAction.PIXELATE
        else:
            detection.action = RedactionAction.FULL_MASK

        box = detection.bounding_box
        expand = 4
        detection.bounding_box = BoundingBox(
            x=max(0, box.x - expand),
            y=max(0, box.y - expand),
            width=box.width + 2 * expand,
            height=box.height + 2 * expand,
        )
