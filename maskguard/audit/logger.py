"""Audit Logger (Skill.md §22): records type/confidence/bounding-box/action/
timestamp/processing-id only. Must never receive the original sensitive text,
full OCR text, passwords, tokens, API keys, credit cards, or ID numbers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..models import Detection


class AuditLogger:
    def __init__(self, log_path: str | Path) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_processing(self, processing_id: str, input_name: str, detections: list[Detection]) -> None:
        entry = {
            "processing_id": processing_id,
            "input": input_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "detections": [self._safe_detection(d) for d in detections],
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _safe_detection(detection: Detection) -> dict:
        box = detection.bounding_box
        return {
            "type": detection.type,
            "confidence": round(detection.confidence, 3),
            "risk_level": detection.risk_level.value,
            "action": detection.action.value,
            "region": [box.x, box.y, box.width, box.height],
            "needs_review": detection.needs_review,
            # deliberately excludes: detection.text
        }
