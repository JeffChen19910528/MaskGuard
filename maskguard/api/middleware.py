"""ASGI-level request body size limit (Phase 8.4 §5/§11).

Root cause this closes: FastAPI resolves `UploadFile`/`Form(...)`
parameters by calling `Request.form()`, which fully consumes the incoming
multipart body (spooling file parts to a `SpooledTemporaryFile` — spilling
to disk above ~1MB) BEFORE the route function body runs at all. That means
`validation.py`'s own `len(data) > max_upload_size_bytes` check — which
does correctly reject an oversized upload — only runs AFTER Starlette has
already received and buffered the entire body. A client sending a
multi-gigabyte body forces the server to buffer/spool that whole amount
before our own check ever gets a chance to say no: exactly the resource-
exhaustion gap Phase 8.4 §5 describes ("do not wait until the entire file
is written before enforcing the limit... an attacker must not be able to
bypass the limit by omitting or falsifying Content-Length").

This middleware sits OUTSIDE all of that, at the raw ASGI level, with TWO
layers:

1. A `Content-Length` fast-path: if the header is present and already
   exceeds the ceiling, reject immediately with a clean `413` — before
   reading a single byte of the body. `Content-Length` is CLIENT-DECLARED
   and untrusted (§5), so this is a courtesy fast-path for well-behaved
   clients, never the sole protection.
2. A streaming byte-counter backstop: counts bytes AS THEY ARRIVE from the
   network (never trusting the header), and once the running total exceeds
   the ceiling, stops the downstream app from consuming any more of the
   stream. This bounds actual memory/disk usage regardless of what
   Content-Length claimed or whether it was even sent — the attacker
   Phase 8.4 §5 specifically calls out (omitted/falsified Content-Length)
   cannot bypass this.

Known, tested, and documented limitation of layer 2: interrupting
Starlette's own multipart parser mid-stream this way is caught by ITS
internal exception handling and surfaces to the client as Starlette's own
generic `400 {"error": {"code": "HTTP_ERROR", ...}}` (via the existing
`StarletteHTTPException` handler — errors.py) rather than a precisely-coded
`413`. This is still a CLEAN, non-leaking, bounded-resource outcome — no
traceback, no crash, no unbounded buffering — just not byte-for-byte the
same error code as layer 1's fast path. Verified directly (see
`tests/api/test_security_hardening.py`).

Pure ASGI (not `BaseHTTPMiddleware`, which itself buffers the whole body to
build a `Request` object — using that here would reintroduce the exact
problem this exists to prevent).
"""
from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class _RequestBodyTooLargeSignal(Exception):
    """Raised from within the wrapped `receive()` once the running byte
    count exceeds the configured ceiling. May be absorbed by downstream
    body-parsing code (see module docstring) rather than reaching this
    middleware's own `except` — either way, no further bytes are read."""


class MaxRequestBodySizeMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return

        # Layer 1: fast Content-Length pre-check (untrusted, best-effort).
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                if declared is not None and declared > self.max_bytes:
                    await _send_413(send, self.max_bytes)
                    return
                break

        # Layer 2: streaming backstop — bounds actual bytes consumed
        # regardless of what (or whether) Content-Length claimed.
        total = 0
        max_bytes = self.max_bytes

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > max_bytes:
                    raise _RequestBodyTooLargeSignal()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _RequestBodyTooLargeSignal:
            await _send_413(send, max_bytes)


async def _send_413(send: Send, max_bytes: int) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "FILE_TOO_LARGE",
                "message": f"Request body exceeds the {max_bytes}-byte limit.",
                "request_id": None,  # the request-id middleware sits INSIDE this one — never assigned yet
            }
        }
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
