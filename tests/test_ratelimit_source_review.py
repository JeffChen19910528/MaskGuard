"""Phase 10.5 §120/§121/§122: static source-review checks — cheap,
durable guardrails against reintroducing an unsafe pattern (raw token
logging, X-Forwarded-For trust, an admin bypass) even after this session
ends. Complements (never replaces) the behavioral tests elsewhere."""
from __future__ import annotations

from pathlib import Path

_RATELIMIT_DIR = Path(__file__).resolve().parent.parent / "maskguard" / "api" / "ratelimit"


def _read_all() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _RATELIMIT_DIR.glob("*.py"))


def test_x_forwarded_for_never_read():
    # §6/§8/§43: only X-Real-IP (and only when explicitly trusted) — never
    # actually READ from `request.headers` (documentation comments
    # explaining the decision are fine and expected).
    source = _read_all().lower()
    assert 'headers.get("x-forwarded-for")' not in source
    assert "headers['x-forwarded-for']" not in source


def test_no_admin_bypass_pattern():
    # §66/§67/§138: no role-based exemption of any kind.
    source = _read_all().lower()
    for forbidden in ("if admin", "is_admin", "bypass_rate_limit", "rate_limit_exempt", "skip_rate_limit"):
        assert forbidden not in source


def test_no_out_of_scope_distributed_backends():
    # Phase 10.5's original "no Redis at all" guard is superseded by
    # Phase 10.6's deliberate, opt-in Redis integration (`redisstate/`,
    # `redis_limiter.py`) — Redis is intentionally out of this list now.
    # Memcache/Postgres/Kafka remain explicitly out of scope for BOTH
    # phases (§88 of Phase 10.6: "do not move Audit SQLite into Redis";
    # never introduce a second unrelated distributed technology).
    source = _read_all().lower()
    for forbidden in ("import memcache", "import psycopg", "import kafka"):
        assert forbidden not in source


def test_no_token_or_secret_variable_names_in_key_derivation():
    # §7/§46: rate-limit keys must never be built from a token/secret —
    # `identity.py`/`dependencies.py` reference only `identity_key`/IP.
    identity_source = (_RATELIMIT_DIR / "identity.py").read_text(encoding="utf-8")
    deps_source = (_RATELIMIT_DIR / "dependencies.py").read_text(encoding="utf-8")
    for forbidden in ("review_token", "access_token", "session_id", "session_cookie.value"):
        assert forbidden not in identity_source
        assert forbidden not in deps_source


def test_logger_call_never_formats_raw_headers_or_body():
    # §53/§54: the ONE logger.info call in dependencies.py logs only
    # request_id/rate_class/anonymous-flag — never headers/cookies/body.
    deps_source = (_RATELIMIT_DIR / "dependencies.py").read_text(encoding="utf-8")
    assert "request.headers" not in deps_source
    assert "request.cookies" not in deps_source
    assert ".body" not in deps_source
