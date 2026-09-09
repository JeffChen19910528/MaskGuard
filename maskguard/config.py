"""Configuration loading. Mirrors the shape documented in Skill.md §21."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.default.yaml"


@dataclass
class OcrConfig:
    engine: str = "local"
    language: list[str] = field(default_factory=lambda: ["zh-TW", "en"])


@dataclass
class DetectionConfig:
    enable_regex: bool = True
    enable_keyword: bool = True
    enable_context: bool = True
    enable_ai: bool = False


@dataclass
class MaskingConfig:
    default_action: str = "blur"
    critical_action: str = "mask"
    verification: bool = True
    max_verification_retries: int = 3


@dataclass
class OutputConfig:
    format: str = "png"
    preserve_metadata: bool = False


@dataclass
class Config:
    ocr: OcrConfig = field(default_factory=OcrConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    masking: MaskingConfig = field(default_factory=MaskingConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    strict_mode: bool = False

    def apply_strict_mode(self) -> None:
        """Strict Mode per Skill.md §40: local-only, no cloud, verification required."""
        self.strict_mode = True
        self.ocr.engine = "local"
        self.detection.enable_ai = self.detection.enable_ai  # AI stays local-only, never cloud
        self.masking.critical_action = "mask"
        self.masking.verification = True
        self.output.preserve_metadata = False


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None) -> Config:
    raw: dict[str, Any] = {}
    if DEFAULT_CONFIG_PATH.exists():
        raw = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    if path is not None:
        override_path = Path(path)
        if override_path.exists():
            override = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
            raw = _merge(raw, override)

    ocr = OcrConfig(**raw.get("ocr", {}))
    detection = DetectionConfig(**raw.get("detection", {}))
    masking = MaskingConfig(**raw.get("masking", {}))
    output = OutputConfig(**raw.get("output", {}))
    return Config(ocr=ocr, detection=detection, masking=masking, output=output)
