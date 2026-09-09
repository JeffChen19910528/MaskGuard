"""Shared data types used across the pipeline (Skill.md §8, §11, §13)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int

    def as_rect(self) -> tuple[int, int, int, int]:
        """Return (left, top, right, bottom)."""
        return self.x, self.y, self.x + self.width, self.y + self.height


@dataclass
class OcrToken:
    """One recognized text token with its position. Never logged verbatim."""

    text: str
    confidence: float
    bounding_box: BoundingBox
    page: int = 0


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        if score >= 0.80:
            return cls.CRITICAL
        if score >= 0.60:
            return cls.HIGH
        if score >= 0.30:
            return cls.MEDIUM
        return cls.LOW


class RedactionAction(str, Enum):
    FULL_MASK = "FULL_MASK"
    BLUR = "BLUR"
    PIXELATE = "PIXELATE"
    PARTIAL_MASK = "PARTIAL_MASK"
    NONE = "NONE"


@dataclass(frozen=True)
class KeywordHit:
    """A risk-raising keyword match (Skill.md §10 Layer 2). Never redacted by
    itself — it only boosts the risk score of detections sharing its line.
    """

    keyword: str
    category: str
    critical: bool  # True for password/token/key/secret-class keywords (§18 fail-safe)
    bounding_box: BoundingBox


@dataclass
class Detection:
    """A single sensitive-data finding, tied back to its OCR token(s)."""

    type: str
    text: str  # kept only in-memory for redaction; must never be logged/serialized raw
    confidence: float
    bounding_box: BoundingBox
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    action: RedactionAction = RedactionAction.NONE
    source_layers: list[str] = field(default_factory=list)
    unknown: bool = False  # True when AI/keyword flagged risk but classification is uncertain
    needs_review: bool = False  # set by the Policy Engine's fail-safe path (§18)
