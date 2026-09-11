"""§25/§29: the API must not reimplement Core, and its temp-file lifecycle
must be airtight — cleaned up on success AND on failure."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from maskguard.api.dependencies import get_service
from maskguard.config import load_config
from maskguard.pipeline import Pipeline

pytestmark = pytest.mark.usefixtures("ocr_env")


def test_api_analyze_result_matches_direct_core_pipeline_call(client, dataset_image, tmp_path):
    """Runs the SAME fixture through (a) the API and (b) a freshly built
    `Pipeline` directly, and checks the detections match — proving the API
    didn't reimplement Detection/Risk/Policy, just called Core."""
    data = dataset_image("TaiwanID_clean.png")

    api_response = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    api_types = sorted(d["type"] for d in api_response.json()["detections"])

    input_path = tmp_path / "input.png"
    input_path.write_bytes(data)
    core_pipeline = Pipeline(load_config())
    core_result = core_pipeline.process(
        str(input_path), str(tmp_path / "out.png"), str(tmp_path / "report.json"), str(tmp_path / "audit.log")
    )
    core_types = sorted(d["type"] for d in core_result.report["detections"])

    assert api_types == core_types


def test_api_risk_and_action_match_direct_core_pipeline_call(client, dataset_image, tmp_path):
    data = dataset_image("TaiwanID_clean.png")

    api_response = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    api_taiwan_id = next(d for d in api_response.json()["detections"] if d["type"] == "TaiwanID")

    input_path = tmp_path / "input.png"
    input_path.write_bytes(data)
    core_result = Pipeline(load_config()).process(
        str(input_path), str(tmp_path / "out.png"), str(tmp_path / "report.json"), str(tmp_path / "audit.log")
    )
    core_taiwan_id = next(d for d in core_result.report["detections"] if d["type"] == "TaiwanID")

    assert api_taiwan_id["risk_level"] == core_taiwan_id["risk"]
    assert api_taiwan_id["action"] == core_taiwan_id["action"]


def test_temp_directory_is_cleaned_up_after_successful_processing(client, dataset_image, monkeypatch):
    created_dirs: list[str] = []
    real_temp_dir = tempfile.TemporaryDirectory

    def _tracking_temp_dir(*args, **kwargs):
        td = real_temp_dir(*args, **kwargs)
        created_dirs.append(td.name)
        return td

    monkeypatch.setattr("maskguard.api.service.tempfile.TemporaryDirectory", _tracking_temp_dir)

    data = dataset_image("Email_clean.png")
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 200

    assert created_dirs, "expected the service to have created a temp directory"
    for path in created_dirs:
        assert not Path(path).exists(), f"temp directory was not cleaned up: {path}"


def test_temp_directory_is_cleaned_up_even_when_core_raises(client, dataset_image, monkeypatch):
    created_dirs: list[str] = []
    real_temp_dir = tempfile.TemporaryDirectory

    def _tracking_temp_dir(*args, **kwargs):
        td = real_temp_dir(*args, **kwargs)
        created_dirs.append(td.name)
        return td

    monkeypatch.setattr("maskguard.api.service.tempfile.TemporaryDirectory", _tracking_temp_dir)

    def _boom(*a, **k):
        raise RuntimeError("simulated Core failure mid-processing")

    service = get_service()
    monkeypatch.setattr(service.pipeline, "process", _boom)

    data = dataset_image("Email_clean.png")
    r = client.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert r.status_code == 500  # the failure surfaced as a proper error response, not a crash

    assert created_dirs, "expected the service to have created a temp directory before failing"
    for path in created_dirs:
        assert not Path(path).exists(), f"temp directory leaked after an exception: {path}"


def test_no_persistent_storage_is_created_by_processing(client, dataset_image, tmp_path, monkeypatch):
    """§30: no database, no permanent image storage. A request must not
    leave anything behind outside its own (already-cleaned-up) temp dir."""
    before = set(Path(tempfile.gettempdir()).glob("maskguard_api_*"))
    data = dataset_image("Email_clean.png")
    client.post("/api/v1/redact", files={"file": ("upload.png", data, "image/png")})
    after = set(Path(tempfile.gettempdir()).glob("maskguard_api_*"))
    assert before == after
