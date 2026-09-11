"""Phase 10.6 §69/§166: MANDATORY PolicyEngine regression — identical
outcome regardless of which node processes the request, and regardless
of REDIS_ENABLED. Real Tesseract required."""
from __future__ import annotations

import pytest

from .conftest import login_as

pytestmark = pytest.mark.usefixtures("ocr_env")


@pytest.mark.parametrize("which_node", ["a", "b"])
def test_passport_reviewer_critical_full_mask_on_either_node(two_nodes, dataset_image, which_node):
    node_a, node_b, token_options = two_nodes
    node = node_a if which_node == "a" else node_b
    login_as(node, token_options, "reviewer-1")

    data = dataset_image("Passport_clean.png")
    resp = node.post("/api/v1/analyze", files={"file": ("upload.png", data, "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    passport = next(d for d in body["detections"] if d["type"] == "Passport")
    assert passport["risk_level"] == "CRITICAL"
    assert passport["action"] == "FULL_MASK"

    redact_resp = node.post("/api/v1/redact", files={"file": ("upload.png", data, "image/png")})
    assert redact_resp.status_code == 200
    verify_resp = node.post("/api/v1/verify", files={"file": ("out.png", redact_resp.content, "image/png")})
    assert verify_resp.status_code == 200
    assert verify_resp.json()["clean"] is True
