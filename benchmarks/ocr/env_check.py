"""OCR environment readiness check for the benchmark framework.

Deliberately a small, self-contained duplicate of the same check used by
`tests/e2e/_environment.py` (not a shared import across the two test-package
directories, to avoid coupling the benchmark suite's collection to the E2E
suite's). Inspects the machine only — never installs or modifies anything.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class OcrEnvironmentReport:
    python_version: str
    pytesseract_importable: bool
    tesseract_binary_path: str | None
    tesseract_version: str | None
    available_languages: list[str] = field(default_factory=list)
    required_languages: tuple[str, ...] = ("eng", "chi_tra")
    missing_languages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (
            self.pytesseract_importable
            and self.tesseract_binary_path is not None
            and self.tesseract_version is not None
            and not self.missing_languages
        )

    def missing_summary(self) -> str:
        missing = []
        if not self.pytesseract_importable:
            missing.append("pytesseract package not importable")
        if self.tesseract_binary_path is None:
            missing.append("tesseract binary not found on PATH")
        elif self.tesseract_version is None:
            missing.append("tesseract binary found but `tesseract --version` failed")
        if self.missing_languages:
            missing.append(f"missing language data: {', '.join(self.missing_languages)}")
        if self.errors:
            missing.append("; ".join(self.errors))
        return " | ".join(missing) if missing else "environment ready"


def check_tesseract_environment() -> OcrEnvironmentReport:
    python_version = sys.version.split()[0]

    try:
        import pytesseract  # noqa: PLC0415
    except ImportError as exc:
        return OcrEnvironmentReport(
            python_version=python_version,
            pytesseract_importable=False,
            tesseract_binary_path=None,
            tesseract_version=None,
            missing_languages=["eng", "chi_tra"],
            errors=[f"pytesseract import failed: {exc}"],
        )

    binary_path = shutil.which("tesseract")
    tesseract_version = None
    available_languages: list[str] = []
    errors: list[str] = []

    if binary_path is not None:
        try:
            tesseract_version = str(pytesseract.get_tesseract_version())
        except Exception as exc:
            errors.append(f"get_tesseract_version failed: {exc}")
        try:
            available_languages = pytesseract.get_languages(config="")
        except Exception as exc:
            errors.append(f"get_languages failed: {exc}")

    required = ("eng", "chi_tra")
    missing_languages = [lang for lang in required if lang not in available_languages]
    if binary_path is None:
        missing_languages = list(required)

    return OcrEnvironmentReport(
        python_version=python_version,
        pytesseract_importable=True,
        tesseract_binary_path=binary_path,
        tesseract_version=tesseract_version,
        available_languages=available_languages,
        missing_languages=missing_languages,
        errors=errors,
    )


def check_paddleocr_available() -> tuple[bool, str | None]:
    """Returns (available, reason_if_not). Never attempts to install anything."""
    try:
        import paddleocr  # noqa: F401,PLC0415
    except ImportError as exc:
        return False, f"paddleocr package not importable: {exc}"
    return True, None


@dataclass
class PaddleEnvironmentReport:
    """Phase 7 environment inspection — never installs or modifies anything."""

    python_version: str
    paddlepaddle_importable: bool
    paddleocr_importable: bool
    paddlepaddle_version: str | None = None
    paddleocr_version: str | None = None
    device: str | None = None  # "gpu" or "cpu"
    gpu_count: int = 0
    model_cache_dir: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.paddlepaddle_importable and self.paddleocr_importable

    def missing_summary(self) -> str:
        if self.ready:
            return "environment ready"
        missing = []
        if not self.paddlepaddle_importable:
            missing.append("paddlepaddle package not importable")
        if not self.paddleocr_importable:
            missing.append("paddleocr package not importable")
        if self.errors:
            missing.append("; ".join(self.errors))
        return " | ".join(missing)


def check_paddleocr_environment() -> PaddleEnvironmentReport:
    """Reports PaddlePaddle/PaddleOCR versions, CPU/GPU, and the model cache
    location — WITHOUT downloading a model or running inference (that only
    happens the first time `PaddleOcrEngine.recognize()` is actually called).
    """
    python_version = sys.version.split()[0]
    errors: list[str] = []

    paddlepaddle_version: str | None = None
    device: str | None = None
    gpu_count = 0
    try:
        import paddle  # noqa: PLC0415

        paddlepaddle_importable = True
        paddlepaddle_version = getattr(paddle, "__version__", "unknown")
        try:
            gpu_count = paddle.device.cuda.device_count() if paddle.is_compiled_with_cuda() else 0
        except Exception as exc:  # pragma: no cover - defensive, CPU-only builds vary in what they expose
            errors.append(f"GPU device query failed: {exc}")
        device = "gpu" if gpu_count > 0 else "cpu"
    except ImportError as exc:
        paddlepaddle_importable = False
        errors.append(f"paddlepaddle import failed: {exc}")

    paddleocr_version: str | None = None
    try:
        import paddleocr  # noqa: PLC0415

        paddleocr_importable = True
        paddleocr_version = getattr(paddleocr, "__version__", "unknown")
    except ImportError as exc:
        paddleocr_importable = False
        errors.append(f"paddleocr import failed: {exc}")

    # PaddleOCR/PaddleX cache their downloaded model weights under the
    # invoking user's home directory by default (never inside this repo).
    cache_candidates = [
        Path.home() / ".paddleocr",
        Path.home() / ".paddlex",
        Path.home() / ".paddlehub",
    ]
    model_cache_dir = next((str(p) for p in cache_candidates if p.exists()), None)

    return PaddleEnvironmentReport(
        python_version=python_version,
        paddlepaddle_importable=paddlepaddle_importable,
        paddleocr_importable=paddleocr_importable,
        paddlepaddle_version=paddlepaddle_version,
        paddleocr_version=paddleocr_version,
        device=device,
        gpu_count=gpu_count,
        model_cache_dir=model_cache_dir,
        errors=errors,
    )
