"""Phase 10.4 §24-33/§50/§51/§68/§83/§84/§92/§94: durable audit storage.

**Storage decision** (see docs/adr/ADR-005-audit.md for full rationale):
SQLite, one file, WAL mode. Chosen over PostgreSQL because MaskGuard's
own architecture is explicitly single-instance today (Phase 9/10.1-10.3's
repeated, disclosed limitation) — a networked database server would add
an entire new operational dependency (credentials, connection security,
backup-of-a-separate-service) this deployment doesn't yet need. SQLite is
part of the Python standard library — zero new dependency (§77's own
"prefer existing Python capabilities" instruction). Chosen over a raw
append-only file because SQLite gives transactional atomicity (§92: an
event is either fully persisted or not at all) and indexed queries
(§38/§39/§94) for free, without hand-rolling either.

**Integrity**: HMAC-SHA256 hash chain (§30-33), using the existing
Docker-secret-file convention for the key
(`AuditSettings.integrity_key`) — never a plain unkeyed hash chain, which
an attacker with full database write access could simply recompute from
the point of tampering forward (§31's own required limitation
disclosure: a keyed HMAC chain means that same attacker, without ALSO
having the key, cannot produce a validly-chained forged continuation,
which a plain hash chain cannot promise).

Append-oriented (§26): this module exposes `append()` and read/query
functions only — there is no `update`/`delete` function for individual
records anywhere in this file, and the SQL schema has no code path that
issues `UPDATE`/`DELETE` against the `audit_events` table.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import AuditSettings
from .models import AuditEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    issuer TEXT,
    request_id TEXT,
    operation TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    result TEXT NOT NULL,
    decision TEXT,
    reason_code TEXT,
    metadata_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_actor_id ON audit_events(actor_id);
CREATE INDEX IF NOT EXISTS idx_audit_request_id ON audit_events(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_operation ON audit_events(operation);
CREATE INDEX IF NOT EXISTS idx_audit_result ON audit_events(result);
"""

_GENESIS_MARKER = b"maskguard-audit-genesis-v1"


def _canonical_fields(event: AuditEvent) -> dict:
    # Explicit field list (never `asdict(event)`, which would silently
    # include prev_hash/hash themselves — those are OUTPUTS of the hash
    # computation, not inputs to it).
    return {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "schema_version": event.schema_version,
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "issuer": event.issuer,
        "request_id": event.request_id,
        "operation": event.operation,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "result": event.result,
        "decision": event.decision,
        "reason_code": event.reason_code,
        "metadata": event.metadata,
    }


def _canonical_json(fields: dict) -> bytes:
    # §30: stable encoding — sorted keys, fixed separators, ASCII-safe
    # (never platform/locale-dependent).
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _compute_hash(key: bytes, prev_hash: str, event: AuditEvent) -> str:
    payload = prev_hash.encode("ascii") + _canonical_json(_canonical_fields(event))
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


class AuditStorageUnavailableError(RuntimeError):
    """§98: raised by `append()`/query functions on any underlying storage
    failure — callers (`service.py`) catch this and apply the documented
    fail-safe policy (§2/§43/§44), never letting it propagate into a
    security decision."""


class AuditStore:
    def __init__(self, db_path: str, integrity_key: bytes) -> None:
        self._db_path = db_path
        self._key = integrity_key
        self._lock = threading.Lock()  # §91: serializes writes within this process — see module docstring's multi-instance note
        Path(db_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)  # §52: not world-readable
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
            os.chmod(self._db_path, 0o600)  # §52: owner read/write only
        except sqlite3.Error as exc:
            raise AuditStorageUnavailableError(str(exc)) from exc

    def _last_hash(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        if row is None:
            return hmac.new(self._key, _GENESIS_MARKER, hashlib.sha256).hexdigest()
        return row[0]

    def append(self, event: AuditEvent) -> AuditEvent:
        """§92: one transaction — fully persisted or not at all. §27/§89/§90:
        `event_id` is UNIQUE; a collision (astronomically unlikely with a
        fresh `uuid4()` per event, but never trusted blindly) raises
        rather than silently overwriting an existing record."""
        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    prev_hash = self._last_hash(conn)
                    computed_hash = _compute_hash(self._key, prev_hash, event)
                    stamped = AuditEvent(**_canonical_fields(event), prev_hash=prev_hash, hash=computed_hash)
                    try:
                        conn.execute(
                            """INSERT INTO audit_events
                               (event_id, timestamp, schema_version, event_type, actor_type, actor_id,
                                issuer, request_id, operation, resource_type, resource_id, result,
                                decision, reason_code, metadata_json, prev_hash, hash)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                stamped.event_id, stamped.timestamp, stamped.schema_version, stamped.event_type,
                                stamped.actor_type, stamped.actor_id, stamped.issuer, stamped.request_id,
                                stamped.operation, stamped.resource_type, stamped.resource_id, stamped.result,
                                stamped.decision, stamped.reason_code, json.dumps(stamped.metadata, ensure_ascii=True),
                                stamped.prev_hash, stamped.hash,
                            ),
                        )
                        conn.execute("COMMIT")
                    except sqlite3.IntegrityError:
                        conn.execute("ROLLBACK")
                        raise AuditStorageUnavailableError(f"duplicate event_id {event.event_id!r}") from None
                    return stamped
            except sqlite3.Error as exc:
                raise AuditStorageUnavailableError(str(exc)) from exc

    def query(
        self,
        *,
        event_type: str | None = None,
        actor_id: str | None = None,
        operation: str | None = None,
        result: str | None = None,
        request_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """§38/§39: strict, parameterized filters only (§50: never string-
        concatenated SQL) — no arbitrary query language exposed."""
        clauses = []
        params: list = []
        for column, value in (
            ("event_type", event_type), ("actor_id", actor_id), ("operation", operation),
            ("result", result), ("request_id", request_id),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""SELECT event_id, timestamp, schema_version, event_type, actor_type, actor_id, issuer,
                          request_id, operation, resource_type, resource_id, result, decision, reason_code,
                          metadata_json, prev_hash, hash
                   FROM audit_events {where} ORDER BY seq DESC LIMIT ? OFFSET ?"""
        params.extend([limit, offset])
        try:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise AuditStorageUnavailableError(str(exc)) from exc

        return [
            AuditEvent(
                event_id=r[0], timestamp=r[1], schema_version=r[2], event_type=r[3], actor_type=r[4],
                actor_id=r[5], issuer=r[6], request_id=r[7], operation=r[8], resource_type=r[9],
                resource_id=r[10], result=r[11], decision=r[12], reason_code=r[13],
                metadata=json.loads(r[14]), prev_hash=r[15], hash=r[16],
            )
            for r in rows
        ]

    def delete_older_than(self, cutoff_iso: str) -> int:
        """§26/§35/§67: the ONLY deletion path in this module — retention
        cleanup, never exposed as a generic per-record DELETE endpoint
        (§26). Deleting the OLDEST segment of the chain means the
        remaining chain's FIRST record's `prev_hash` no longer matches
        anything still present — `verify_integrity()` treats this as an
        expected, documented discontinuity (a "checkpoint" boundary, §35)
        rather than reporting a false tamper alarm; see that function's
        own docstring."""
        with self._lock:
            try:
                with self._connect() as conn:
                    cur = conn.execute("DELETE FROM audit_events WHERE timestamp < ?", (cutoff_iso,))
                    return cur.rowcount
            except sqlite3.Error as exc:
                raise AuditStorageUnavailableError(str(exc)) from exc

    def verify_integrity(self) -> tuple[bool, str | None]:
        """§30/§84: walks the ENTIRE chain, recomputing each record's HMAC
        from its own fields + the PREVIOUS record's stored hash, and
        comparing against the stored hash. Returns `(True, None)` if every
        record checks out, or `(False, <event_id of the first mismatch>)`.

        §35 retention interaction: after `delete_older_than()` has run,
        the OLDEST remaining record's `prev_hash` refers to a
        now-deleted record and will not match "genesis" — this function
        treats the FIRST record's `prev_hash` as trusted-as-stored (not
        re-derivable once its predecessor is gone) and verifies the chain
        from THAT point forward. This is an accepted, documented
        consequence of retention deletion (§35: "do not simply delete the
        beginning of a hash chain and claim the remaining chain is still
        independently verifiable [from genesis]") — the remaining segment
        IS still internally tamper-evident, but the very first surviving
        record's own prev_hash is not itself re-verifiable against
        anything.
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """SELECT event_id, timestamp, schema_version, event_type, actor_type, actor_id, issuer,
                              request_id, operation, resource_type, resource_id, result, decision, reason_code,
                              metadata_json, prev_hash, hash FROM audit_events ORDER BY seq ASC"""
                ).fetchall()
        except sqlite3.Error as exc:
            raise AuditStorageUnavailableError(str(exc)) from exc

        expected_prev = None
        for r in rows:
            event = AuditEvent(
                event_id=r[0], timestamp=r[1], schema_version=r[2], event_type=r[3], actor_type=r[4],
                actor_id=r[5], issuer=r[6], request_id=r[7], operation=r[8], resource_type=r[9],
                resource_id=r[10], result=r[11], decision=r[12], reason_code=r[13],
                metadata=json.loads(r[14]), prev_hash=r[15], hash=r[16],
            )
            if expected_prev is not None and event.prev_hash != expected_prev:
                return False, event.event_id
            recomputed = _compute_hash(self._key, event.prev_hash, event)
            if recomputed != event.hash:
                return False, event.event_id
            expected_prev = event.hash
        return True, None
