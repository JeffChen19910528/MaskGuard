from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._environment import check_ocr_environment

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


_E2E_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items):
    """Every test collected under tests/e2e/ is auto-marked `e2e`, so the
    default `pytest` run (which excludes `-m e2e` via pyproject.toml addopts)
    skips this whole directory without needing @pytest.mark.e2e on every test.

    NOTE: pytest_collection_modifyitems in *any* conftest.py runs against the
    WHOLE session's item list, not just this directory — so this must filter
    by path itself rather than assuming it's only called with local items.
    """
    for item in items:
        if _E2E_DIR in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def ocr_env():
    report = check_ocr_environment()
    if not report.ready:
        pytest.skip(f"ENVIRONMENT NOT READY: {report.missing_summary()}")
    return report


@pytest.fixture(scope="session")
def fixtures_manifest() -> dict:
    manifest_path = FIXTURES_DIR / "manifest.json"
    if not manifest_path.exists():
        pytest.skip(
            "test fixtures not generated — run: python scripts/generate_test_images.py"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_path():
    def _path(name: str) -> Path:
        path = FIXTURES_DIR / name
        if not path.exists():
            pytest.skip(f"missing fixture {name} — run: python scripts/generate_test_images.py")
        return path

    return _path
