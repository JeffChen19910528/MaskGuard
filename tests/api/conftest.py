from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchmarks.ocr.env_check import check_tesseract_environment
from maskguard.api.app import create_app
from maskguard.api.dependencies import get_service
from maskguard.api.ratelimit.config import get_rate_limit_settings
from maskguard.api.ratelimit.dependencies import get_rate_limiter

_DATASET_DIR = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "results" / "dataset"
_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "manifest.json"


def pytest_collection_modifyitems(items):
    """Auto-mark everything under tests/api/ as `api` (excluded from the
    default `pytest` run via pyproject.toml addopts, same pattern as
    tests/e2e's `e2e` marker and tests/ocr_benchmark's `benchmark` marker)."""
    this_dir = Path(__file__).resolve().parent
    for item in items:
        if this_dir in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.api)


@pytest.fixture()
def client():
    """A fresh app/TestClient per test. Building the app does NOT require
    Tesseract (Pipeline/LocalOcrEngine construction doesn't probe the
    binary) — only tests that actually process an image need `ocr_env`."""
    get_service.cache_clear()
    # Phase 10.5: every OTHER test module's client fixture (auth/
    # authorization/audit/ratelimit conftests) clears its OWN settings
    # caches on entry/exit, but a plain `client` test here has no such
    # override — it must see rate limiting in its TRUE default (disabled)
    # state, never leftover RATE_LIMIT_ENABLED=true / stale bucket state
    # from an earlier test module that ran first in this session.
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()
    app = create_app()
    # raise_server_exceptions=False: an unhandled exception must surface as
    # a normal HTTP 500 response (per our own exception handler, §17) that
    # tests can assert on — not re-raised into the test process, which is
    # TestClient's debugging-oriented default.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    get_service.cache_clear()
    get_rate_limit_settings.cache_clear()
    get_rate_limiter.cache_clear()


@pytest.fixture(scope="session")
def ocr_env():
    report = check_tesseract_environment()
    if not report.ready:
        pytest.skip(f"ENVIRONMENT NOT READY: {report.missing_summary()}")
    return report


@pytest.fixture()
def dataset_image():
    def _load(name: str) -> bytes:
        path = _DATASET_DIR / name
        if not path.exists():
            pytest.skip(f"missing benchmark fixture {name} — run: python -m benchmarks.ocr.run")
        return path.read_bytes()

    return _load


@pytest.fixture(scope="session")
def fixtures_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        pytest.skip("test fixtures manifest not generated — run: python scripts/generate_test_images.py")
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
