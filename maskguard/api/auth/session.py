"""Phase 10.2 §19-22/§49/§76-78: server-side session + pending-auth-transaction
storage, behind a small interface (§20) so Phase 10.6 can swap in a shared
store (Redis/DB) without touching callers — this phase's implementation is
explicitly process-local, documented as such, never claimed to be
multi-instance-safe.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict

from .models import AuthenticatedIdentity, PendingAuthTransaction, SessionRecord

#: §75: cryptographically secure, unpredictable, non-sequential — never a
#: user ID/email/timestamp/incrementing integer (§21). 32 bytes = 256 bits
#: of entropy, URL-safe encoded.
def _generate_opaque_id() -> str:
    return secrets.token_urlsafe(32)


class SessionStore(ABC):
    """Interface Phase 10.6 will re-implement against shared storage
    (docs/adr/ADR-004-review-state.md's reasoning applies identically
    here — see docs/authentication-implementation.md "Multi-instance
    limitation")."""

    @abstractmethod
    def create(self, identity: AuthenticatedIdentity, idle_timeout: int, absolute_timeout: int) -> SessionRecord: ...

    @abstractmethod
    def get(self, session_id: str, idle_timeout: int) -> SessionRecord | None: ...

    @abstractmethod
    def delete(self, session_id: str) -> None: ...

    @abstractmethod
    def rotate(self, old_session_id: str, idle_timeout: int, absolute_timeout: int) -> SessionRecord | None:
        """§49: invalidates `old_session_id` and mints a brand-new,
        independently-random session id carrying the same identity —
        used on login (fixation protection, §21/§50) and reserved for a
        future privilege-elevation event (§49, not triggered by anything
        in this phase, since no privilege levels exist yet)."""


class InMemorySessionStore(SessionStore):
    """Phase 10.2's ONLY implementation: process-local, in-memory,
    bounded (§76). NOT safe for multi-instance deployment — see
    docs/authentication-implementation.md."""

    def __init__(self, max_sessions: int) -> None:
        self._max_sessions = max_sessions
        self._sessions: OrderedDict[str, SessionRecord] = OrderedDict()
        self._lock = threading.Lock()

    def _evict_if_full(self) -> None:
        # §76: bounded memory — evict the OLDEST entry (simple, predictable
        # policy; not a substitute for rate limiting, documented as such).
        while len(self._sessions) >= self._max_sessions:
            self._sessions.popitem(last=False)

    def create(self, identity: AuthenticatedIdentity, idle_timeout: int, absolute_timeout: int) -> SessionRecord:
        now = time.time()
        record = SessionRecord(
            session_id=_generate_opaque_id(),
            identity=identity,
            created_at=now,
            last_seen_at=now,
            absolute_expires_at=now + absolute_timeout,
        )
        with self._lock:
            self._evict_if_full()
            self._sessions[record.session_id] = record
        return record

    def get(self, session_id: str, idle_timeout: int) -> SessionRecord | None:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                return None
            if record.is_expired(idle_timeout):
                del self._sessions[session_id]
                return None
            record.last_seen_at = time.time()
            self._sessions.move_to_end(session_id)
            return record

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def rotate(self, old_session_id: str, idle_timeout: int, absolute_timeout: int) -> SessionRecord | None:
        with self._lock:
            old = self._sessions.pop(old_session_id, None)
            if old is None or old.is_expired(idle_timeout):
                return None
            now = time.time()
            new_record = SessionRecord(
                session_id=_generate_opaque_id(),  # independently random — never derived from old_session_id (§21/§49)
                identity=old.identity,
                created_at=now,
                last_seen_at=now,
                absolute_expires_at=now + absolute_timeout,
            )
            self._evict_if_full()
            self._sessions[new_record.session_id] = new_record
            return new_record


class PendingTransactionStore(ABC):
    @abstractmethod
    def create(self, state: str, nonce: str, code_verifier: str, return_path: str) -> PendingAuthTransaction: ...

    @abstractmethod
    def consume(self, transaction_id: str, ttl_seconds: int) -> PendingAuthTransaction | None:
        """§79: one-time use — returns the transaction and DELETES it in
        the same call. A second consume() with the same id returns None."""


class InMemoryPendingTransactionStore(PendingTransactionStore):
    """§77: bounded, TTL'd. Process-local, same multi-instance caveat as
    `InMemorySessionStore`."""

    def __init__(self, max_transactions: int) -> None:
        self._max = max_transactions
        self._transactions: OrderedDict[str, PendingAuthTransaction] = OrderedDict()
        self._lock = threading.Lock()

    def create(self, state: str, nonce: str, code_verifier: str, return_path: str) -> PendingAuthTransaction:
        txn = PendingAuthTransaction(
            transaction_id=_generate_opaque_id(),
            state=state,
            nonce=nonce,
            code_verifier=code_verifier,
            created_at=time.time(),
            return_path=return_path,
        )
        with self._lock:
            while len(self._transactions) >= self._max:
                self._transactions.popitem(last=False)
            self._transactions[txn.transaction_id] = txn
        return txn

    def consume(self, transaction_id: str, ttl_seconds: int) -> PendingAuthTransaction | None:
        with self._lock:
            txn = self._transactions.pop(transaction_id, None)  # §79: removed unconditionally — replay always fails
        if txn is None:
            return None
        if txn.is_expired(ttl_seconds):
            return None
        return txn


# ---------------------------------------------------------------------------
# Phase 10.6: Redis-backed implementations of the SAME two interfaces above.
# Selected at construction time (auth/dependencies.py) when REDIS_ENABLED —
# every method signature/semantic matches the in-memory classes exactly, so
# no caller (routes.py, dependencies.py, authorization/dependencies.py)
# needs to know or care which backend is active.
# ---------------------------------------------------------------------------


def _serialize_identity(identity: AuthenticatedIdentity) -> dict:
    return {
        "subject": identity.subject, "issuer": identity.issuer,
        "authenticated_at": identity.authenticated_at, "provider": identity.provider,
        "email": identity.email, "display_name": identity.display_name,
    }


def _serialize_record(record: SessionRecord) -> str:
    return json.dumps(
        {
            "session_id": record.session_id, "identity": _serialize_identity(record.identity),
            "created_at": record.created_at, "last_seen_at": record.last_seen_at,
            "absolute_expires_at": record.absolute_expires_at,
        },
        separators=(",", ":"),
    )


def _deserialize_record(raw: str) -> SessionRecord:
    data = json.loads(raw)
    identity = AuthenticatedIdentity(**data["identity"])
    return SessionRecord(
        session_id=data["session_id"], identity=identity, created_at=data["created_at"],
        last_seen_at=data["last_seen_at"], absolute_expires_at=data["absolute_expires_at"],
    )


class RedisSessionStore(SessionStore):
    """Phase 10.6 §7/§10/§11/§12/§13: cross-instance session state.

    Key: `<namespace>session:<opaque-id>` — NEVER `<namespace>session:<email>`
    (§10); the opaque, high-entropy `session_id` (unchanged generation,
    §8) is the only lookup key, exactly as the cookie already carries.
    Stores ONLY what `SessionRecord` already holds — subject/issuer/
    timestamps/provider/display metadata — never an access/ID/refresh
    token (§7/§76: there was never a token in this record to begin with,
    Phase 10.2's own design already minimized this before Redis existed).

    TTL is bounded by the session's OWN absolute expiry (§11) — the Redis
    key expires no later than `absolute_expires_at`, so state can never
    outlive its own security lifetime even if `delete()` is never called
    (e.g. a crashed request that never reached `logout`).

    Any Redis failure raises `RedisUnavailableError` (via `safe_call`) —
    NEVER caught here, NEVER treated as "no session" (§18/§95: that would
    be fail-open). The caller (`auth/dependencies.py`) is responsible for
    converting this into a safe `503 DEPENDENCY_UNAVAILABLE` — see that
    module's docstring.
    """

    def __init__(self, client, namespace: str) -> None:
        from ..redisstate.client import safe_call  # local import: auth/ stays import-independent of redisstate/ except here

        self._client = client
        self._prefix = f"{namespace}session:"
        self._safe_call = safe_call

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def create(self, identity: AuthenticatedIdentity, idle_timeout: int, absolute_timeout: int) -> SessionRecord:
        now = time.time()
        record = SessionRecord(
            session_id=_generate_opaque_id(), identity=identity, created_at=now,
            last_seen_at=now, absolute_expires_at=now + absolute_timeout,
        )
        ttl = max(1, int(absolute_timeout))
        self._safe_call("session_create", self._client.set, self._key(record.session_id), _serialize_record(record), ex=ttl)
        return record

    def get(self, session_id: str, idle_timeout: int) -> SessionRecord | None:
        raw = self._safe_call("session_get", self._client.get, self._key(session_id))
        if raw is None:
            return None
        try:
            record = _deserialize_record(raw)
        except (ValueError, KeyError, TypeError):
            return None  # corrupted/foreign value -> treat as absent, NEVER as authenticated
        now = time.time()
        if record.is_expired(idle_timeout, now):
            self.delete(session_id)
            return None
        record.last_seen_at = now
        # §11: sliding idle-timeout window, never extended past the
        # session's own absolute expiry.
        new_ttl = int(min(idle_timeout, record.absolute_expires_at - now))
        if new_ttl > 0:
            self._safe_call("session_touch", self._client.set, self._key(session_id), _serialize_record(record), ex=new_ttl)
        return record

    def delete(self, session_id: str) -> None:
        # §12/§14/§17/§149: logout — removes shared state outright, so
        # every OTHER instance's very next lookup of this session_id
        # observes it as gone (no per-instance caching anywhere, §102).
        self._safe_call("session_delete", self._client.delete, self._key(session_id))

    def rotate(self, old_session_id: str, idle_timeout: int, absolute_timeout: int) -> SessionRecord | None:
        old = self.get(old_session_id, idle_timeout)
        if old is None:
            return None
        self.delete(old_session_id)
        now = time.time()
        new_record = SessionRecord(
            session_id=_generate_opaque_id(), identity=old.identity, created_at=now,
            last_seen_at=now, absolute_expires_at=now + absolute_timeout,
        )
        ttl = max(1, int(absolute_timeout))
        self._safe_call("session_rotate", self._client.set, self._key(new_record.session_id), _serialize_record(new_record), ex=ttl)
        return new_record


class RedisPendingTransactionStore(PendingTransactionStore):
    """Phase 10.6: distributes the pending OIDC-transaction store too —
    NOT explicitly named in the phase brief's state catalog (§6), but
    directly implied by §60 ("do not implement sticky sessions... test
    that Request 1 -> A, Request 2 -> B still works") and §116-117 (real
    load balancing, no sticky sessions): without this, `/auth/login`
    landing on Node A and `/auth/callback` landing on Node B would ALWAYS
    fail (the transaction id would only exist in Node A's memory) any
    time a load balancer round-robins the two requests of a single login
    across instances — a real, obvious multi-instance correctness gap,
    not "unrelated state" (§6's caution against moving unrelated state
    into Redis does not apply here: this is part of the SAME
    authentication flow).

    One-time consumption uses Redis `GETDEL` (atomic get+delete in a
    single command, Redis >= 6.2) — a second `consume()` for the same
    transaction_id always finds nothing, exactly matching the in-memory
    store's `pop()` semantics (§79 replay protection unchanged).
    """

    def __init__(self, client, namespace: str) -> None:
        from ..redisstate.client import safe_call

        self._client = client
        self._prefix = f"{namespace}txn:"
        self._safe_call = safe_call

    def create(self, state: str, nonce: str, code_verifier: str, return_path: str) -> PendingAuthTransaction:
        txn = PendingAuthTransaction(
            transaction_id=_generate_opaque_id(), state=state, nonce=nonce,
            code_verifier=code_verifier, created_at=time.time(), return_path=return_path,
        )
        payload = json.dumps(
            {
                "transaction_id": txn.transaction_id, "state": txn.state, "nonce": txn.nonce,
                "code_verifier": txn.code_verifier, "created_at": txn.created_at, "return_path": txn.return_path,
            },
            separators=(",", ":"),
        )
        # A generous, fixed upper-bound TTL (the caller's real
        # `transaction_ttl_seconds` is enforced separately by `consume()`
        # below via `is_expired()` — this key-level TTL only guarantees an
        # ABANDONED transaction is eventually reclaimed, never relied on
        # as the authoritative expiry check).
        self._safe_call("txn_create", self._client.set, self._prefix + txn.transaction_id, payload, ex=3600)
        return txn

    def consume(self, transaction_id: str, ttl_seconds: int) -> PendingAuthTransaction | None:
        raw = self._safe_call("txn_consume", self._client.getdel, self._prefix + transaction_id)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            txn = PendingAuthTransaction(**data)
        except (ValueError, KeyError, TypeError):
            return None
        if txn.is_expired(ttl_seconds):
            return None
        return txn
