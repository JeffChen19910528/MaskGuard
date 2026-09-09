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
