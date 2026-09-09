"""Processing Report (Skill.md §25). Must never contain the original
sensitive text — only type/confidence/risk/action/region."""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Detection
from ..verification.verification_engine import VerificationResult


def build_report(
    processing_id: str,
    input_path: str,
    output_path: str,
    detections: list[Detection],
    verification: VerificationResult,
) -> dict:
    return {
        "processing_id": processing_id,
        "input": input_path,
        "output": output_path,
        "detections": [
            {
                "type": d.type,
                "confidence": round(d.confidence, 3),
                "risk": d.risk_level.value,
                "action": d.action.value,
                "region": [d.bounding_box.x, d.bounding_box.y, d.bounding_box.width, d.bounding_box.height],
                "needs_review": d.needs_review,
            }
            for d in detections
        ],
        "verification": {
            "status": verification.status,
            "attempts": verification.attempts,
            "residual_count": verification.residual_count,
            "needs_human_review": verification.needs_human_review,
        },
    }


def write_report(report: dict, path: str | Path) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
