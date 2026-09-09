from __future__ import annotations

import pytest

from benchmarks.ocr.env_check import check_tesseract_environment


def pytest_collection_modifyitems(items):
    """Auto-mark everything collected under tests/ocr_benchmark/ as
    `benchmark`. Scoped by path because pytest_collection_modifyitems in any
    conftest.py runs against the WHOLE session's items, not just this dir
    (see tests/e2e/conftest.py for the same guard and why it's needed)."""
    from pathlib import Path

    this_dir = Path(__file__).resolve().parent
    for item in items:
        if this_dir in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.benchmark)


@pytest.fixture(scope="session")
def tesseract_env():
    report = check_tesseract_environment()
    if not report.ready:
        pytest.skip(f"ENVIRONMENT NOT READY: {report.missing_summary()}")
    return report
