"""Signed, short-lived review context (Phase 8.3 §5/§6/§30-33).

MaskGuard's API is intentionally stateless (Phase 8.1 §30) — no database,
no persistent review storage. But Human Review must never let the browser
dictate a detection's type/risk/action/confidence back to the backend
(§30/§31): "the browser should only submit review intent... Backend should
resolve the original detection from trusted processing context... use a
signed review context/token." This module is that token.

`/api/v1/analyze` mints one (`issue()`) over the EXACT `Detection` list
Core just produced — type/bbox/risk_level/action/confidence, generated
`detection_id`s, and the source image's dimensions. Never the raw matched
text, which was never in that response to begin with (see mapping.py).
`/api/v1/review` calls `verify_and_consume()` to recover that trusted list
— the browser can only reference a `detection_id` it already saw (to accept
or reject it) or submit a brand-new MANUAL detection's `type`/`bbox`
(validated separately in `review_service.py`); it can never make the
backend believe a detection had a different type/risk/action/confidence
than Core actually assigned it, because those values never round-trip
through the client — they live only inside the signed token.

Signing: HMAC-SHA256 over a compact JSON payload, keyed by a secret
generated once per process (`secrets.token_bytes`) and held only in memory
— consistent with "no persistent storage" (Phase 8.3 §5/§31: "choose the
simplest secure architecture compatible with current stateless design...
do NOT add Redis/database merely for this"). A process restart invalidates
every in-flight review token, which is an acceptable, documented
consequence of staying stateless (see README "Known limitations") — an
in-flight review is short-lived by design (§32) and simply needs to be
restarted (re-`/analyze`) if the server restarts mid-review.

Replay protection (§33): `verify_and_consume()` claims each token's
signature via a pluggable `ReplayStore` on first successful use and
refuses a second submission. Default (`InMemoryReplayStore`): an
in-memory "spent" set, swept lazily by expiry — unchanged since Phase
8.3, still the ONLY store for single-instance deployments.

Phase 10.6 update: when `REDIS_ENABLED=true` (multi-instance
deployment), `RedisReplayStore` replaces it with an atomic `SET NX EX`
claim shared across every API instance — this does NOT contradict Phase
8.3's original "do not add Redis merely for this" guidance, which was
specifically about a SINGLE-instance deployment having no need for
external state; once multiple instances exist, an in-memory set on ONE
instance cannot see a replay attempt routed to a DIFFERENT instance, so
shared state becomes a correctness requirement, not an optional
enhancement. The token's OWN security model (HMAC signature, TTL,
identity binding) is completely unchanged either way — only WHERE the
one-time-use marker lives changes (see `ReplayStore`/`RedisReplayStore`
below and docs/distributed-state-implementation.md).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


class ReviewTokenError(Exception):
    """Carries the API error `code` to raise (see errors.py)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class TokenDetection:
    detection_id: str
    type: str
    risk_level: str
    action: str
    confidence: float
    needs_review: bool
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ReviewContext:
    detections: tuple[TokenDetection, ...]
    image_width: int
    image_height: int
    issued_at: float
    expires_at: float


class ReplayStore(ABC):
    """Phase 10.6 §21/§22/§23/§24: the one-time-consumption primitive
    `verify_and_consume()` uses — swappable so the SECURITY MODEL (HMAC
    signature, TTL, identity binding — all still enforced entirely in
    `verify_and_consume()` below) never changes, only WHERE the replay
    marker lives (§21: "distribute ONLY the replay state... do not move
    the security model into Redis")."""

    @abstractmethod
    def try_consume(self, fingerprint: str, ttl_seconds: int) -> bool:
        """Atomically claims `fingerprint` for one-time use. Returns True
        on the FIRST successful claim, False if already claimed. Must
        raise `ReplayStoreUnavailableError` — never silently return True
        — if the check itself could not be performed (§30: "NEVER treat
        token as unused" on infrastructure failure)."""


class ReplayStoreUnavailableError(RuntimeError):
    """§30/§31: raised instead of a fail-open `True` when the replay
    check itself cannot be performed."""


class InMemoryReplayStore(ReplayStore):
    """Unchanged Phase 8.3/10.3 behavior: an in-memory dict of
    `signature -> expires_at`, swept lazily. Default when Redis is
    disabled — byte-for-byte the same as this module's pre-Phase-10.6
    design (the class body was extracted, not rewritten)."""

    def __init__(self) -> None:
        self._spent: dict[str, float] = {}
        self._lock = threading.Lock()

    def try_consume(self, fingerprint: str, ttl_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            expired = [sig for sig, exp in self._spent.items() if exp < now]
            for sig in expired:
                del self._spent[sig]
            if fingerprint in self._spent:
                return False
            self._spent[fingerprint] = now + max(1, ttl_seconds)
            return True


class RedisReplayStore(ReplayStore):
    """Phase 10.6 §23/§24/§75: atomic `SET NX EX` — the simplest correct
    primitive (§24 explicitly lists it first). A key existing already
    means some OTHER request already won the race; Redis's own atomicity
    guarantees EXACTLY ONE caller across ANY number of instances ever
    receives `True` for a given `fingerprint`, with no window for two
    concurrent requests to both observe "unused" (§24's own explicit
    warning against `GET` then `SET`).

    `fingerprint` is the token's own HMAC-SHA256 signature — already
    computed by `verify_and_consume()` for verification, never the raw
    token body/detections — satisfying §75 ("store only the minimum
    required information... a fingerprint is sufficient... appropriate
    keyed construction": an HMAC output is exactly that, not raw
    content, and cannot be used to reconstruct or forge anything).
    """

    def __init__(self, client, namespace: str) -> None:
        from .redisstate.client import safe_call

        self._client = client
        self._prefix = f"{namespace}review:"
        self._safe_call = safe_call

    def try_consume(self, fingerprint: str, ttl_seconds: int) -> bool:
        from .redisstate.client import RedisUnavailableError

        try:
            result = self._safe_call(
                "review_replay_claim", self._client.set,
                self._prefix + fingerprint, "1", nx=True, ex=max(1, int(ttl_seconds)),
            )
        except RedisUnavailableError as exc:
            raise ReplayStoreUnavailableError(str(exc)) from exc
        return bool(result)


@dataclass
class ReviewTokenIssuer:
    ttl_seconds: int = 600
    #: Phase 9 §16: a deployment MAY supply its own secret (e.g. from a
    #: Docker secret file) so tokens survive a container restart within a
    #: single instance's lifetime being irrelevant here — restarts still
    #: invalidate in-flight reviews either way (§15/§48, single-instance
    #: architecture unchanged) — the real reason to allow this is so an
    #: operator can rotate/inspect the secret deliberately rather than it
    #: always being an opaque, unobservable, auto-generated value. `None`
    #: (development default) generates a fresh random one per process,
    #: exactly as Phase 8.3/8.4 already did.
    secret: bytes | None = None
    #: Phase 10.6 §21: `None` (default) -> `InMemoryReplayStore()`,
    #: preserving exact prior-phase behavior. A Redis-backed store is
    #: injected by `dependencies.py`/`service.py` only when
    #: `REDIS_ENABLED=true` — the token's own HMAC/TTL/identity-binding
    #: security model (below) is completely unaffected either way.
    replay_store: "ReplayStore | None" = None
    _secret: bytes = field(init=False)

    def __post_init__(self) -> None:
        self._secret = self.secret if self.secret is not None else secrets.token_bytes(32)
        if self.replay_store is None:
            self.replay_store = InMemoryReplayStore()

    def issue(
        self, detections: list[TokenDetection], image_width: int, image_height: int, identity_key: str | None = None
    ) -> str:
        """Phase 10.3 §25/§26: `identity_key` (the CALLER-side
        `AuthenticatedIdentity.identity_key`, i.e. `issuer|subject` —
        never email) is embedded in the signed payload ONLY when this
        deployment has an authenticated caller to bind to (`None` when
        OIDC is disabled, preserving Phase 8.3/9 behavior exactly).
        `verify_and_consume()` then requires the SAME identity to submit
        the review — closing the cross-user review attack (§27) without
        redesigning the token's existing HMAC/TTL/single-use architecture
        (§25: "do not redesign distributed review state")."""
        now = time.time()
        payload = {
            "d": [asdict(d) for d in detections],
            "w": image_width,
            "h": image_height,
            "iat": now,
            "exp": now + self.ttl_seconds,
            "idk": identity_key,
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        body = base64.urlsafe_b64encode(raw).decode("ascii")
        signature = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{body}.{signature}"

    def verify_and_consume(self, token: str, identity_key: str | None = None) -> ReviewContext:
        """Phase 10.3 §25-27: `identity_key` is the SUBMITTING caller's
        `AuthenticatedIdentity.identity_key` (None when OIDC is
        disabled). If the token was issued bound to an identity (§25),
        the submitting identity must match EXACTLY — a different
        authenticated user (or an unauthenticated caller, if OIDC is
        somehow enabled for issuance but not enforced at submission)
        presenting an otherwise-valid, unexpired, not-yet-spent token is
        rejected (§27's cross-user review attack). A token issued with no
        binding (`idk: None` — the OIDC-disabled case) is never subject to
        this check, preserving Phase 8.3/9 behavior exactly."""
        if not token or "." not in token:
            raise ReviewTokenError("INVALID_REVIEW", "Malformed review token.")
        body, _, signature = token.rpartition(".")

        expected_signature = hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise ReviewTokenError("INVALID_REVIEW", "Review token signature is invalid.")

        try:
            raw = base64.urlsafe_b64decode(body.encode("ascii"))
            payload = json.loads(raw)
            detections = tuple(TokenDetection(**d) for d in payload["d"])
            image_width = int(payload["w"])
            image_height = int(payload["h"])
            issued_at = float(payload["iat"])
            expires_at = float(payload["exp"])
            bound_identity_key = payload.get("idk")
        except Exception:
            raise ReviewTokenError("INVALID_REVIEW", "Malformed review token.") from None

        if time.time() > expires_at:
            raise ReviewTokenError("REVIEW_EXPIRED", "This review context has expired; please analyze the image again.")

        # Phase 10.3 §27: cross-user review attack — a token bound to one
        # identity cannot be redeemed by a different one, even though it
        # is otherwise cryptographically valid and unexpired. Checked
        # BEFORE marking spent, so a mismatched attempt doesn't burn the
        # legitimate owner's still-valid token.
        if bound_identity_key is not None and bound_identity_key != identity_key:
            raise ReviewTokenError("INVALID_REVIEW", "This review context does not belong to the current user.")

        # Mark spent only once the token is confirmed well-formed, not
        # already expired, AND identity-bound correctly — an expired/
        # malformed/wrong-identity token was never usable, so it need not
        # occupy (or, worse, prematurely burn) the replay-guard slot
        # (§27's own comment above still applies unchanged: this ordering
        # is what stops a mismatched-identity attempt from burning the
        # legitimate owner's still-valid token).
        #
        # Phase 10.6 §23/§24: atomic claim via `ReplayStore.try_consume`
        # — `InMemoryReplayStore` (default) or `RedisReplayStore`
        # (REDIS_ENABLED). `ReplayStoreUnavailableError` propagates
        # UNCAUGHT here (never treated as "unused" — §30) for the caller
        # (routes/review.py) to convert into a safe 503.
        ttl_seconds = max(1, int(expires_at - time.time()) + 1)
        if not self.replay_store.try_consume(signature, ttl_seconds):
            raise ReviewTokenError("REVIEW_CONFLICT", "This review has already been submitted.")

        return ReviewContext(
            detections=detections, image_width=image_width, image_height=image_height,
            issued_at=issued_at, expires_at=expires_at,
        )
