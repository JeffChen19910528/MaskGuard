"""Phase 10.5 §6/§7/§8/§43/§118: rate-limit KEY derivation. Never keyed
by email, session ID, access/ID/review token, or any browser-supplied
identity header (`X-User`/`X-Role`/`X-Permission`/arbitrary cookies) —
only the trusted authenticated identity (Phase 10.2 `AuthenticatedIdentity
.identity_key`, resolved server-side from the validated session cookie)
or the network-level client address.
"""
from __future__ import annotations

from fastapi import Request

from .config import RateLimitSettings

#: §30: bound an attacker-controlled header value's contribution to a key
#: — even when trusted (only read under `trust_proxy_headers=True`), a
#: pathological length is truncated rather than stored/hashed unbounded.
_MAX_IP_LENGTH = 64


def client_ip(request: Request, settings: RateLimitSettings) -> str:
    """§8/§118: `X-Real-IP` is read ONLY when `trust_proxy_headers` is
    true — see `config.py`'s field docstring for exactly why that is safe
    in this project's Docker/Nginx topology and not assumed anywhere
    else. `X-Forwarded-For` is never read (client-appendable list, a
    materially weaker guarantee than a header Nginx unconditionally
    overwrites). Falls back to the ASGI-level TCP peer address
    (`request.client.host`) — never spoofable by request headers."""
    if settings.trust_proxy_headers:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()[:_MAX_IP_LENGTH]
    client = request.client
    return client.host[:_MAX_IP_LENGTH] if client else "unknown"
