"""MaskGuard HTTP API layer (Phase 8.1). Thin wrapper around Core
(`maskguard.pipeline.Pipeline`) — see `service.py`'s module docstring for
the exact boundary. Not imported by `maskguard/__init__.py` or `cli.py`, so
`pip install maskguard` (CLI-only) never requires fastapi/uvicorn/pydantic
(see the `api` extra in pyproject.toml)."""

#: API contract version — bumped independently of `maskguard.__version__`
#: (the Core package version) since the two are allowed to evolve at
#: different rates (§23: Core model != API contract).
__api_version__ = "1.0.0"
