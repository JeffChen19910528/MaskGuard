"""Environment readiness check for real-OCR E2E tests.

This does NOT install or modify anything — it only inspects what is already
on the machine (pytesseract import, tesseract binary, language data) and
reports what is missing so E2E tests can SKIP with a clear reason instead of
failing or silently passing.
"""
from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field


@dataclass
class OcrEnvironmentReport:
    python_version: str
    pytesseract_importable: bool
    pytesseract_version: str | None
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


def check_ocr_environment() -> OcrEnvironmentReport:
    python_version = sys.version.split()[0]

    pytesseract_importable = False
    pytesseract_version = None
    try:
        import pytesseract  # noqa: PLC0415

        pytesseract_importable = True
        pytesseract_version = getattr(pytesseract, "__version__", "unknown")
    except ImportError as exc:
        return OcrEnvironmentReport(
            python_version=python_version,
            pytesseract_importable=False,
            pytesseract_version=None,
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
        except Exception as exc:  # pytesseract raises its own TesseractNotFoundError subclass
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
        pytesseract_importable=pytesseract_importable,
        pytesseract_version=pytesseract_version,
        tesseract_binary_path=binary_path,
        tesseract_version=tesseract_version,
        available_languages=available_languages,
        missing_languages=missing_languages,
        errors=errors,
    )


if __name__ == "__main__":
    report = check_ocr_environment()
    print(f"Python version        : {report.python_version}")
    print(f"pytesseract importable: {report.pytesseract_importable} (version {report.pytesseract_version})")
    print(f"tesseract binary path  : {report.tesseract_binary_path}")
    print(f"tesseract --version    : {report.tesseract_version}")
    print(f"available languages    : {report.available_languages}")
    print(f"missing languages      : {report.missing_languages}")
    print(f"READY FOR E2E          : {report.ready}")
    if not report.ready:
        print(f"MISSING                : {report.missing_summary()}")
