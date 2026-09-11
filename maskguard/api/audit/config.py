"""Phase 10.4 §24/§34/§67: audit storage/retention/integrity configuration.
Same env-driven pattern as `maskguard/api/config.py`/`maskguard/api/auth/config.py`
— no duplicate configuration system.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from ..auth.config import _bool_env
from ..config import _int_env, _secret_env


class InsecureAuditConfigError(RuntimeError):
    """§79 of Phase 10.1's fail-closed discipline, applied here: a
    malformed retention value or missing integrity key in production is a
    hard startup failure, never a silent fallback."""


@dataclass(frozen=True)
class AuditSettings:
    #: Master switch (§0, matching the opt-in pattern Phase 10.2/10.3
    #: already established). When False, no audit events are written and
    #: no `/api/v1/audit` route is registered — zero behavior change for
    #: a deployment that hasn't opted in.
    audit_enabled: bool = field(default_factory=lambda: _bool_env("AUDIT_ENABLED", False))
    #: §24/§51/§119: a fixed, server-controlled path — never derived from
    #: a request. SQLite (see docs/adr/ADR-005-audit.md for the storage
    #: decision) — a single file, not a directory a path-traversal
    #: attempt could escape. Default is DELIBERATELY NOT under `/tmp` —
    #: this deployment's own `docker-compose*.yml` mounts `/tmp` as an
    #: ephemeral `tmpfs` for image-processing temp files (Phase 9), which
    #: would silently discard "durable" audit records on every container
    #: restart. `/var/lib/maskguard-audit` is backed by a real, separate,
    #: persistent named Docker volume (`docker-compose*.yml`) — never the
    #: same mount as uploaded/redacted image temp files (§119).
    db_path: str = field(default_factory=lambda: os.environ.get("AUDIT_DB_PATH", "/var/lib/maskguard-audit/audit.db"))
    #: §30/§32: HMAC key for the hash chain — from the existing
    #: Docker-secret-file convention (`_secret_env`, same helper Phase 9's
    #: review-token secret and Phase 10.2's OIDC client secret already
    #: use). `None` in development auto-generates one per process
    #: (chain verifiable only within that process's lifetime — documented
    #: limitation, same class as the review-token secret's Phase 8.3
    #: process-restart caveat).
    integrity_key: str | None = field(
        default_factory=lambda: _secret_env("AUDIT_INTEGRITY_KEY_FILE", "AUDIT_INTEGRITY_KEY")
    )
    #: §34: default 365 days — a common baseline enterprise-audit
    #: retention period (documented, not claimed as a compliance
    #: guarantee for any specific regulatory framework). Configurable per
    #: deployment.
    retention_days: int = field(default_factory=lambda: _int_env("AUDIT_RETENTION_DAYS", 365))
    #: §23: bounds a single event's total serialized size.
    max_event_bytes: int = field(default_factory=lambda: _int_env("AUDIT_MAX_EVENT_BYTES", 8192))
    #: §22: metadata dict bounds.
    max_metadata_keys: int = field(default_factory=lambda: _int_env("AUDIT_MAX_METADATA_KEYS", 16))
    max_metadata_key_length: int = field(default_factory=lambda: _int_env("AUDIT_MAX_METADATA_KEY_LENGTH", 64))
    max_metadata_value_length: int = field(default_factory=lambda: _int_env("AUDIT_MAX_METADATA_VALUE_LENGTH", 256))
    #: §39: query API bounds.
    max_query_page_size: int = field(default_factory=lambda: _int_env("AUDIT_MAX_QUERY_PAGE_SIZE", 200))
    max_query_range_days: int = field(default_factory=lambda: _int_env("AUDIT_MAX_QUERY_RANGE_DAYS", 90))


@lru_cache
def get_audit_settings() -> AuditSettings:
    return AuditSettings()


def validate_production_audit_config(environment: str, settings: AuditSettings) -> None:
    """§43/§67/§79: fail closed at startup — never lazily on first audit
    write."""
    if not settings.audit_enabled:
        return
    if settings.retention_days <= 0:
        raise InsecureAuditConfigError("AUDIT_RETENTION_DAYS must be a positive integer.")
    if settings.retention_days > 3650:
        # §67: "reject absurdly large values that create uncontrolled
        # storage growth" — 10 years is already generous; beyond that is
        # almost certainly a misconfiguration (e.g. an accidental extra
        # zero), not a deliberate policy.
        raise InsecureAuditConfigError("AUDIT_RETENTION_DAYS exceeds the sane maximum (3650 days / 10 years).")
    if environment != "production":
        return
    if not settings.integrity_key:
        raise InsecureAuditConfigError(
            "AUDIT_ENABLED=true in production requires AUDIT_INTEGRITY_KEY(_FILE) to be set — "
            "refusing to start with an auto-generated, unobservable, process-local integrity key "
            "in production (it would make the hash chain unverifiable across restarts)."
        )
    if len(settings.integrity_key) < 32:
        raise InsecureAuditConfigError("AUDIT_INTEGRITY_KEY is shorter than the required 32 characters.")
