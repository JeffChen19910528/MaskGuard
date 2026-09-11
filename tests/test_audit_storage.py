"""Phase 10.4 §26-33/§85/§89-92: durable storage, append-only enforcement,
hash-chain integrity, tamper detection, concurrency, retention. Pure unit
tests against a real (temp-file) SQLite database — no Tesseract, no HTTP,
no Docker.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from maskguard.api.audit.config import AuditSettings
from maskguard.api.audit.event_types import AUTH_LOGIN_SUCCESS, IMAGE_ANALYZE
from maskguard.api.audit.models import RESULT_SUCCESS
from maskguard.api.audit.sanitizer import build_event
from maskguard.api.audit.storage import AuditStorageUnavailableError, AuditStore


@pytest.fixture()
def store(tmp_path):
    return AuditStore(str(tmp_path / "audit.db"), b"test-integrity-key-not-for-production")


def _event(settings, **overrides):
    kwargs = dict(
        event_type=IMAGE_ANALYZE, actor_type="user", actor_id="iss|sub", issuer="iss",
        request_id="req-1", operation="image.analyze", resource_type="image", resource_id="p-1",
        result=RESULT_SUCCESS, metadata={},
    )
    kwargs.update(overrides)
    return build_event(settings, **kwargs)


@pytest.fixture()
def settings():
    return AuditSettings(audit_enabled=True)


def test_append_and_query_roundtrip(store, settings):
    event = store.append(_event(settings))
    results = store.query(limit=10)
    assert len(results) == 1
    assert results[0].event_id == event.event_id
    assert results[0].hash is not None
    assert results[0].prev_hash is not None


def test_events_are_hash_chained(store, settings):
    e1 = store.append(_event(settings))
    e2 = store.append(_event(settings))
    assert e2.prev_hash == e1.hash
    assert e1.hash != e2.hash


def test_fresh_store_integrity_passes(store, settings):
    for _ in range(5):
        store.append(_event(settings))
    ok, bad = store.verify_integrity()
    assert ok is True
    assert bad is None


def test_empty_store_integrity_passes(store):
    ok, bad = store.verify_integrity()
    assert ok is True


# --- §31/§85: tamper detection ---------------------------------------------


def _tamper(db_path: str, sql: str, params: tuple = ()) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def test_modified_record_detected(store, settings, tmp_path):
    store.append(_event(settings))
    e2 = store.append(_event(settings))
    store.append(_event(settings))
    _tamper(str(tmp_path / "audit.db"), "UPDATE audit_events SET result = 'DENIED' WHERE event_id = ?", (e2.event_id,))
    ok, bad = store.verify_integrity()
    assert ok is False
    assert bad == e2.event_id


def test_modified_actor_detected(store, settings, tmp_path):
    e1 = store.append(_event(settings, actor_id="iss|sub"))
    _tamper(str(tmp_path / "audit.db"), "UPDATE audit_events SET actor_id = 'iss|attacker' WHERE event_id = ?", (e1.event_id,))
    ok, bad = store.verify_integrity()
    assert ok is False


def test_modified_timestamp_detected(store, settings, tmp_path):
    e1 = store.append(_event(settings))
    _tamper(str(tmp_path / "audit.db"), "UPDATE audit_events SET timestamp = '1999-01-01T00:00:00+00:00' WHERE event_id = ?", (e1.event_id,))
    ok, bad = store.verify_integrity()
    assert ok is False


def test_modified_metadata_detected(store, settings, tmp_path):
    e1 = store.append(_event(settings, metadata={"detection_count": 1}))
    _tamper(str(tmp_path / "audit.db"), 'UPDATE audit_events SET metadata_json = ? WHERE event_id = ?', ('{"detection_count": 999}', e1.event_id))
    ok, bad = store.verify_integrity()
    assert ok is False


def test_deleted_record_detected(store, settings, tmp_path):
    store.append(_event(settings))
    e2 = store.append(_event(settings))
    store.append(_event(settings))
    _tamper(str(tmp_path / "audit.db"), "DELETE FROM audit_events WHERE event_id = ?", (e2.event_id,))
    ok, bad = store.verify_integrity()
    assert ok is False  # the surviving record after e2 now has a prev_hash pointing to nothing present


def test_forged_event_insertion_detected(store, settings, tmp_path):
    e1 = store.append(_event(settings))
    # Attacker inserts a record with a plausible-looking but unsigned hash.
    _tamper(
        str(tmp_path / "audit.db"),
        """INSERT INTO audit_events
           (event_id, timestamp, schema_version, event_type, actor_type, actor_id, issuer, request_id,
            operation, resource_type, resource_id, result, decision, reason_code, metadata_json, prev_hash, hash)
           VALUES ('forged-event-id','2026-01-01T00:00:00+00:00',1,'IMAGE_ANALYZE','user','forged|actor',NULL,
                   NULL,'image.analyze',NULL,NULL,'SUCCESS',NULL,NULL,'{}',?,'0000000000000000000000000000000000000000000000000000000000000000')""",
        (e1.hash,),
    )
    ok, bad = store.verify_integrity()
    assert ok is False


def test_reordered_events_detected(store, settings, tmp_path):
    """Swapping two records' `seq` (insertion order) breaks the chain
    since each record's `prev_hash` was computed against the PRIOR
    record's actual hash at write time."""
    e1 = store.append(_event(settings, operation="first"))
    e2 = store.append(_event(settings, operation="second"))
    db_path = str(tmp_path / "audit.db")
    conn = sqlite3.connect(db_path)
    seq1 = conn.execute("SELECT seq FROM audit_events WHERE event_id=?", (e1.event_id,)).fetchone()[0]
    seq2 = conn.execute("SELECT seq FROM audit_events WHERE event_id=?", (e2.event_id,)).fetchone()[0]
    conn.execute("UPDATE audit_events SET seq = ? WHERE event_id = ?", (10_000, e1.event_id))
    conn.execute("UPDATE audit_events SET seq = ? WHERE event_id = ?", (seq1, e2.event_id))
    conn.execute("UPDATE audit_events SET seq = ? WHERE event_id = ?", (seq2, e1.event_id))
    conn.commit()
    conn.close()
    ok, bad = store.verify_integrity()
    assert ok is False


def test_wrong_integrity_key_fails_verification(tmp_path, settings):
    """§32: a chain built with one key cannot be verified with a
    different one — the key itself is the actual protection, not the
    hash-chain STRUCTURE alone."""
    path = str(tmp_path / "audit.db")
    store_a = AuditStore(path, b"key-A-not-for-production-use-only")
    store_a.append(_event(settings))
    store_b = AuditStore(path, b"key-B-different-key-entirely-here")
    ok, bad = store_b.verify_integrity()
    assert ok is False


# --- §27/§89/§90: event ID uniqueness --------------------------------------


def test_duplicate_event_id_rejected_not_overwritten(store, settings):
    from maskguard.api.audit.models import AuditEvent

    e1 = store.append(_event(settings))
    duplicate = AuditEvent(
        event_id=e1.event_id, timestamp=e1.timestamp, schema_version=1, event_type=IMAGE_ANALYZE,
        actor_type="user", actor_id="attacker|forged", issuer=None, request_id=None, operation="forged",
        resource_type=None, resource_id=None, result=RESULT_SUCCESS, decision=None, reason_code=None, metadata={},
    )
    with pytest.raises(AuditStorageUnavailableError):
        store.append(duplicate)
    # Original record must be untouched.
    results = store.query(limit=10)
    assert len(results) == 1
    assert results[0].actor_id == "iss|sub"


# --- §91/§92: concurrent writes ---------------------------------------------


def test_concurrent_appends_produce_a_valid_unbroken_chain(store, settings):
    errors = []

    def _write():
        try:
            for _ in range(5):
                store.append(_event(settings))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_write) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    results = store.query(limit=100)
    assert len(results) == 20
    ok, bad = store.verify_integrity()
    assert ok is True, f"chain broken after concurrent writes, first bad event: {bad}"


# --- §26/§35: append-only / retention deletion -----------------------------


def test_no_update_or_delete_path_for_individual_records(store):
    """§26: the module's public surface has no per-record mutate/delete
    function — only `append`, `query`, `delete_older_than` (bulk,
    retention-only), and `verify_integrity`."""
    public_methods = {name for name in dir(AuditStore) if not name.startswith("_")}
    assert public_methods == {"append", "query", "delete_older_than", "verify_integrity"}


def test_retention_deletion_removes_only_old_records(store, settings):
    store.append(_event(settings))
    remaining = store.append(_event(settings))
    # Backdate the first record directly (simulating it being genuinely old).
    import sqlite3 as _sqlite3

    db_path = store._db_path
    old_ts = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    conn = _sqlite3.connect(db_path)
    conn.execute("UPDATE audit_events SET timestamp = ? WHERE seq = 1", (old_ts,))
    conn.commit()
    conn.close()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    deleted = store.delete_older_than(cutoff)
    assert deleted == 1
    results = store.query(limit=10)
    assert len(results) == 1
    assert results[0].event_id == remaining.event_id


def test_chain_segment_after_retention_deletion_remains_internally_verifiable(store, settings, tmp_path):
    """§35: after deleting the oldest record, the REMAINING chain is
    still internally tamper-evident — verified by then tampering with a
    SURVIVING record and confirming detection still works."""
    store.append(_event(settings))
    e2 = store.append(_event(settings))
    e3 = store.append(_event(settings))

    old_ts = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    db_path = str(tmp_path / "audit.db")
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE audit_events SET timestamp = ? WHERE seq = 1", (old_ts,))
    conn.commit()
    conn.close()
    store.delete_older_than((datetime.now(timezone.utc) - timedelta(days=365)).isoformat())

    # Tamper with a record that's still present.
    _tamper(db_path, "UPDATE audit_events SET result = 'DENIED' WHERE event_id = ?", (e3.event_id,))
    ok, bad = store.verify_integrity()
    assert ok is False
    assert bad == e3.event_id
