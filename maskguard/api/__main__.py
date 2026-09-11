"""`python -m maskguard.api` — local development launcher.

Binds to 127.0.0.1 by default (never 0.0.0.0 — see README.md's Security
Notes for what changes before exposing this beyond localhost)."""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("MASKGUARD_API_HOST", "127.0.0.1")
    port = int(os.environ.get("MASKGUARD_API_PORT", "8000"))
    uvicorn.run("maskguard.api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
