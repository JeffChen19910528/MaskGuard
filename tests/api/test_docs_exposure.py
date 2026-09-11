"""Phase 10.7 §29: interactive API documentation must not be exposed in
production."""
from __future__ import annotations

from fastapi.testclient import TestClient

from maskguard.api.app import create_app
from maskguard.api.config import get_settings
from maskguard.api.dependencies import get_service


def _client_for_env(monkeypatch, environment: str) -> TestClient:
    monkeypatch.setenv("MASKGUARD_ENV", environment)
    if environment == "production":
        monkeypatch.setenv("MASKGUARD_REVIEW_TOKEN_SECRET", "a" * 40)
    get_settings.cache_clear()
    get_service.cache_clear()
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    return client


def test_docs_disabled_in_production(monkeypatch):
    client = _client_for_env(monkeypatch, "production")
    with client:
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    get_settings.cache_clear()
    get_service.cache_clear()


def test_docs_available_in_development(monkeypatch):
    client = _client_for_env(monkeypatch, "development")
    with client:
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200
    get_settings.cache_clear()
    get_service.cache_clear()
