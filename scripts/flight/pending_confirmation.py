#!/usr/bin/env python3
"""Durable confirmation barrier for messages addressed to settled sessions.

The store is deliberately independent from a scheduler or a transport. A
caller may use it from auto, queue, steer, or restart paths, but none of those
paths can deliver a message without an explicit confirmation.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PENDING_CONFIRMATION = "pending_confirmation"
TERMINAL_STATES = frozenset(
    {
        "cancelled",
        "expired",
        "delivered",
        "delivery_failed",
        "delivery_unknown",
        "reactivated",
    }
)
VALID_MODES = frozenset({"auto", "queue", "steer", "restart"})


class ConfirmationError(ValueError):
    """Raised when a pending confirmation cannot be accepted."""


class Authorization:
    """Verifiable caller identity and credential for a privileged operation."""

    __slots__ = ("actor", "token")

    def __init__(self, actor: str, token: str):
        """Create an immutable-by-convention authorization value.

        Before: actor and token are supplied by the caller for verification.
        During: both values are retained without contacting a transport.
        After: the verifier can inspect the identity and credential.
        """
        self.actor = actor
        self.token = token


def content_hash(content: str) -> str:
    """Return the stable SHA-256 hash used by confirmation requests.

    Before: content is the exact message body intended for delivery.
    During: the UTF-8 bytes are hashed without normalization or transport work.
    After: a lowercase hexadecimal SHA-256 digest is returned.
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _utc(now: datetime | None = None) -> datetime:
    """Normalize an optional clock value to timezone-aware UTC.

    Before: now is absent or a datetime supplied by a caller or test clock.
    During: a missing value is read from the UTC system clock and naive values
        are interpreted as UTC.
    After: a timezone-aware UTC datetime is returned.
    """
    value = datetime.now(timezone.utc) if now is None else now
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    """Serialize a datetime with second precision.

    Before: value is a datetime representing a store timestamp.
    During: value is normalized to UTC and formatted as ISO-8601.
    After: an unambiguous UTC timestamp string is returned.
    """
    return _utc(value).isoformat(timespec="seconds")


class PendingConfirmationStore:
    """JSONL-backed pending confirmation store with atomic state transitions."""

    _lock = threading.RLock()

    def __init__(
        self,
        path: Path,
        clock: Callable[[], datetime] | None = None,
        verifier: Callable[[Authorization], bool] | None = None,
        authorized_actors: frozenset[str] | None = None,
    ):
        """Create a store at path without waking or contacting a target.

        Before: path names the durable JSONL store; clock and verifier are optional.
        During: the path, deterministic clock, and fail-closed authorization
            policy are retained; no file is read.
        After: the store is ready for create, confirm, cancel, and audit calls.
        """
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.verifier = verifier
        self.authorized_actors = authorized_actors

    def _claim_path(self, pending_id: str) -> Path:
        """Return the durable exclusive claim path for one pending request.

        Before: pending_id is a store-generated identifier.
        During: the identifier is used only to derive a sibling claim path.
        After: the returned path can be claimed with OS-level O_EXCL.
        """
        return self.path.with_name(self.path.name + "." + pending_id + ".claim")

    def _delivered_path(self, pending_id: str) -> Path:
        """Return the durable one-shot delivery token path.

        Before: pending_id identifies a confirmed request.
        During: the identifier is used only to derive a sibling delivery path.
        After: the returned path can be consumed with OS-level O_EXCL.
        """
        return self.path.with_name(self.path.name + "." + pending_id + ".delivered")

    def _authorize(self, authorization: Authorization | None) -> str | None:
        """Validate actor and credential through the injected verifier.

        Before: authorization may be absent, malformed, or supplied by an
            untrusted caller.
        During: actor presence, actor allowlist, token presence, and verifier
            result are checked without accepting a caller-provided boolean.
        After: None means authorized; otherwise a stable error name is returned.
        """
        if authorization is None or not authorization.actor.strip():
            return "missing_actor"
        if (
            self.authorized_actors is not None
            and authorization.actor not in self.authorized_actors
        ):
            return "unauthorized_actor"
        if not authorization.token:
            return "bad_credential"
        if self.verifier is None:
            return "bad_credential"
        try:
            valid = self.verifier(authorization)
        except Exception:
            valid = False
        return None if valid else "bad_credential"

    def _acquire_claim(self, pending_id: str, authorization: Authorization) -> bool:
        """Claim a pending request once with an OS-level exclusive create.

        Before: validation has passed and no delivery has started.
        During: O_CREAT|O_EXCL races all processes on the same store directory.
        After: True identifies the sole claimant; the claim file remains durable.
        """
        claim_path = self._claim_path(pending_id)
        try:
            fd = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps({"pending_id": pending_id, "actor": authorization.actor})
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ConfirmationError("pending claim cannot be written") from exc
        return True

    def _acquire_delivery_token(
        self, pending_id: str, authorization: Authorization
    ) -> bool:
        """Consume the one-shot OS-level delivery token.

        Before: confirmation authorization has passed and the request is confirmed.
        During: O_CREAT|O_EXCL races all delivery workers across processes.
        After: True identifies the only worker allowed to invoke transport.
        """
        delivered_path = self._delivered_path(pending_id)
        try:
            fd = os.open(delivered_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps({"pending_id": pending_id, "actor": authorization.actor})
                    + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ConfirmationError("delivery token cannot be written") from exc
        return True

    def _now(self) -> datetime:
        """Read and normalize the configured clock.

        Before: the store has a callable clock.
        During: the callable is invoked once.
        After: a timezone-aware UTC datetime is returned.
        """
        return _utc(self.clock())

    def _read(self) -> list[dict[str, Any]]:
        """Read valid JSONL entries, treating a missing file as empty.

        Before: the store may be absent or contain durable JSONL entries.
        During: UTF-8 JSON objects are loaded and malformed lines are rejected.
        After: a list of dictionaries is returned, or a clear store error.
        """
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            entries = [json.loads(line) for line in lines if line.strip()]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConfirmationError("pending store is unreadable") from exc
        if not all(isinstance(entry, dict) for entry in entries):
            raise ConfirmationError("pending store contains a non-object entry")
        return entries

    def _write(self, entries: list[dict[str, Any]]) -> None:
        """Atomically replace the JSONL store with entries.

        Before: entries contains the complete next store state.
        During: a UTF-8 temporary file is flushed and replaced in the same
            directory, so readers observe either the old or new state.
        After: the durable store contains exactly entries.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(
                prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    for entry in entries:
                        handle.write(json.dumps(entry, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        except OSError as exc:
            raise ConfirmationError("pending store cannot be written") from exc

    @staticmethod
    def _latest(
        entries: list[dict[str, Any]], pending_id: str
    ) -> dict[str, Any] | None:
        """Return the latest snapshot for pending_id.

        Before: entries are store records and pending_id is supplied by a caller.
        During: records are scanned in append order.
        After: the latest pending snapshot is returned, or None if unknown.
        """
        latest = None
        for entry in entries:
            if entry.get("pending_id") == pending_id and entry.get("kind") in {
                "pending",
                "transition",
            }:
                latest = entry
        return latest

    def create_pending(
        self,
        *,
        target_thread_id: str,
        target_lifecycle_version: str,
        content: str,
        client_request_id: str,
        expires_in_seconds: int = 300,
        mode: str = "auto",
        enqueue: Callable[[dict[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        """Create a SYSTEM-issued pending confirmation without target activity.

        Before: the target is settled, identifiers are non-empty, and mode is
            one of auto, queue, steer, or restart.
        During: the exact content hash and expiry are recorded in one atomic
            store update; no wake, enqueue, retry, or transport is called.
            The optional enqueue argument is an observation seam and is never called.
        After: a pending_confirmation response containing the public fields is
            returned.
        """
        if (
            not target_thread_id
            or not target_lifecycle_version
            or not client_request_id
        ):
            raise ConfirmationError(
                "target, lifecycle version, and client request are required"
            )
        if mode not in VALID_MODES:
            raise ConfirmationError("invalid delivery mode")
        if expires_in_seconds <= 0:
            raise ConfirmationError("expiry must be positive")
        now = self._now()
        pending_id = "pending-" + uuid.uuid4().hex
        response = {
            "status": PENDING_CONFIRMATION,
            "pending_id": pending_id,
            "target_thread_id": target_thread_id,
            "target_lifecycle_version": target_lifecycle_version,
            "content_hash": content_hash(content),
            "client_request_id": client_request_id,
            "expires_at": _iso(now + timedelta(seconds=expires_in_seconds)),
            "issuer": "SYSTEM",
            "mode": mode,
        }
        entry = {"kind": "pending", "created_at": _iso(now), **response}
        with self._lock:
            entries = self._read()
            self._write([*entries, entry])
        return dict(response)

    def _transition(
        self, pending_id: str, state: str, now: datetime, note: str
    ) -> dict[str, Any]:
        """Append a terminal transition while holding the store CAS lock.

        Before: the caller holds the process lock and state is terminal-ready.
        During: the latest snapshot is copied with a new terminal state.
        After: the transition is durably appended and returned.
        """
        entries = self._read()
        current = self._latest(entries, pending_id)
        if current is None:
            raise ConfirmationError("unknown pending_id")
        if current["status"] != "pending_confirmation":
            return dict(current)
        transitioned = {
            **current,
            "kind": "transition",
            "status": state,
            "transitioned_at": _iso(now),
            "note": note,
        }
        self._write([*entries, transitioned])
        return transitioned

    def confirm_once(
        self,
        *,
        pending_id: str,
        content_hash_value: str,
        target_lifecycle_version: str,
        authorization: Authorization | None,
    ) -> dict[str, Any]:
        """Authorize and mark a pending request confirmed exactly once.

        Before: the caller supplies verifiable authorization, the expected hash
            and lifecycle version; transport is deliberately absent.
        During: checks run before an OS-exclusive confirmation claim, then the
            request is marked confirmed without invoking transport.
        After: exactly one process returns confirmed and attempt_delivery owns
            the subsequent one-shot transport operation.
        """
        with self._lock:
            entries = self._read()
            current = self._latest(entries, pending_id)
            if current is None:
                return {"status": "error", "error": "unknown_pending_id"}
            if current["status"] != "pending_confirmation":
                return {"status": "error", "error": "already_terminal"}
            auth_error = self._authorize(authorization)
            if auth_error is not None:
                return {"status": "error", "error": auth_error}
            if current["content_hash"] != content_hash_value:
                return {"status": "error", "error": "content_hash_mismatch"}
            if current["target_lifecycle_version"] != target_lifecycle_version:
                return {"status": "error", "error": "lifecycle_version_mismatch"}
            now = self._now()
            if now >= datetime.fromisoformat(current["expires_at"]):
                self._transition(pending_id, "expired", now, "ttl")
                return {"status": "error", "error": "expired"}
            if not self._acquire_claim(pending_id, authorization):
                return {"status": "error", "error": "already_terminal"}
            claimed = {
                **current,
                "kind": "transition",
                "status": "confirmed",
                "confirmed_at": _iso(now),
                "actor": authorization.actor,
                "evidence_digest": hashlib.sha256(
                    authorization.token.encode("utf-8")
                ).hexdigest(),
            }
            self._write([*entries, claimed])
        return {"status": "confirmed", "pending_id": pending_id}

    @staticmethod
    def _envelope(current: dict[str, Any], pending_id: str) -> dict[str, str]:
        """Build the SYSTEM broker envelope without target impersonation.

        Before: current is the validated pending snapshot.
        During: only broker identity and immutable delivery identifiers are copied.
        After: a transport-ready envelope is returned.
        """
        return {
            "sender": "SYSTEM",
            "target_thread_id": current["target_thread_id"],
            "content_hash": current["content_hash"],
            "pending_id": pending_id,
        }

    def _record_delivery_intent(
        self, pending_id: str, actor: str, evidence_digest: str
    ) -> None:
        """Persist delivery intent before invoking an external transport.

        Before: the exclusive delivery token is consumed and state is confirmed.
        During: an intent transition with actor and evidence is atomically appended.
        After: a crash during transport is distinguishable from a delivered result.
        """
        with self._lock:
            entries = self._read()
            current = self._latest(entries, pending_id)
            if current is None:
                raise ConfirmationError("unknown pending_id")
            intent = {
                **current,
                "status": "delivery_intent",
                "intent_at": _iso(self._now()),
                "actor": actor,
                "evidence_digest": evidence_digest,
            }
            self._write([*entries, intent])

    def _record_delivery_unknown(self, pending_id: str) -> None:
        """Convert an unresolved intent into an audited terminal unknown state.

        Before: a later attempt finds delivery_intent without delivered or failed.
        During: delivery_unknown and its audit event are appended atomically.
        After: further attempts return delivery_unknown without transport.
        """
        with self._lock:
            entries = self._read()
            current = self._latest(entries, pending_id)
            if current is None:
                raise ConfirmationError("unknown pending_id")
            if current["status"] == "delivery_unknown":
                return
            now = self._now()
            unknown = {**current, "status": "delivery_unknown", "unknown_at": _iso(now)}
            audit = {
                "kind": "audit",
                "event": "delivery_unknown",
                "pending_id": pending_id,
                "at": _iso(now),
                "actor": current.get("actor", ""),
                "evidence_digest": current.get("evidence_digest", ""),
            }
            self._write([*entries, unknown, audit])

    def attempt_delivery(
        self,
        pending_id: str,
        transport: Callable[[dict[str, str]], Any],
        authorization: Authorization | None,
    ) -> dict[str, Any]:
        """Deliver one confirmed request through the exclusive one-shot gate.

        Before: a scheduler, queued run, retry, or caller supplies a pending id,
            transport, and verifiable authorization.
        During: authorization and confirmed state are checked, then a durable
            `.delivered` O_EXCL token is consumed before transport is invoked.
        After: the first worker records delivered; later workers return
            already_delivered without touching transport.
        """
        auth_error = self._authorize(authorization)
        if auth_error is not None:
            return {"status": "error", "error": auth_error}
        with self._lock:
            current = self._latest(self._read(), pending_id)
            if current is None:
                return {"status": "error", "error": "unknown_pending_id"}
            if current["status"] in {"delivered", "delivery_failed"}:
                return {"status": "error", "error": "already_delivered"}
            if current["status"] == "delivery_unknown":
                return {"status": "error", "error": "delivery_unknown"}
            if current["status"] == "delivery_intent":
                self._record_delivery_unknown(pending_id)
                return {"status": "error", "error": "delivery_unknown"}
            if current["status"] != "confirmed":
                return {"status": "error", "error": "not_confirmed"}
            if not self._acquire_delivery_token(pending_id, authorization):
                return {"status": "error", "error": "already_delivered"}
            evidence_digest = hashlib.sha256(
                authorization.token.encode("utf-8")
            ).hexdigest()
            self._record_delivery_intent(
                pending_id, authorization.actor, evidence_digest
            )
            envelope = self._envelope(current, pending_id)
        try:
            transport(envelope)
        except Exception as exc:
            self._record_delivery_failure(
                pending_id,
                str(exc),
                authorization.actor,
                evidence_digest,
            )
            return {"status": "error", "error": "delivery_failed"}
        self._record_delivery_success(
            pending_id,
            authorization.actor,
            evidence_digest,
        )
        return {"status": "delivered", "pending_id": pending_id}

    def _record_delivery_success(
        self, pending_id: str, actor: str, evidence_digest: str
    ) -> None:
        """Record delivered and audit it after transport success.

        Before: the exclusive delivery token has completed transport successfully.
        During: delivered and its audit record are appended under the process lock.
        After: the request is durably terminal and cannot be delivered again.
        """
        with self._lock:
            entries = self._read()
            current = self._latest(entries, pending_id)
            if current is None:
                raise ConfirmationError("unknown pending_id")
            now = self._now()
            transition = {
                **current,
                "status": "delivered",
                "delivered_at": _iso(now),
                "actor": actor,
                "evidence_digest": evidence_digest,
            }
            audit = {
                "kind": "audit",
                "event": "delivered",
                "pending_id": pending_id,
                "actor": actor,
                "evidence_digest": evidence_digest,
                "at": _iso(now),
            }
            self._write([*entries, transition, audit])

    def _record_delivery_failure(
        self, pending_id: str, detail: str, actor: str, evidence_digest: str
    ) -> None:
        """Record an audited terminal transport failure.

        Before: transport raised after this process acquired the exclusive claim.
        During: delivery_failed and its audit record are appended atomically.
        After: the request cannot be retried implicitly and the failure is queryable.
        """
        with self._lock:
            entries = self._read()
            current = self._latest(entries, pending_id)
            if current is None:
                raise ConfirmationError("unknown pending_id")
            now = self._now()
            transition = {
                **current,
                "status": "delivery_failed",
                "failed_at": _iso(now),
                "failure": detail,
            }
            audit = {
                "kind": "audit",
                "event": "delivery_failed",
                "pending_id": pending_id,
                "detail": detail,
                "actor": actor,
                "evidence_digest": evidence_digest,
                "at": _iso(now),
            }
            self._write([*entries, transition, audit])

    def cancel(self, pending_id: str, reason: str = "cancelled") -> dict[str, Any]:
        """Cancel a pending request as a terminal non-delivery state.

        Before: pending_id identifies a request and reason describes the audit.
        During: the request is transitioned atomically under the CAS lock.
        After: cancellation is durable and subsequent confirmation cannot deliver.
        """
        with self._lock:
            return self._transition(pending_id, "cancelled", self._now(), reason)

    def expire(self, pending_id: str) -> dict[str, Any]:
        """Expire a request when its TTL has elapsed.

        Before: pending_id identifies a request whose TTL may have elapsed.
        During: expiration is checked and a terminal transition is recorded.
        After: an expired request cannot be confirmed or delivered.
        """
        with self._lock:
            entries = self._read()
            current = self._latest(entries, pending_id)
            if current is None:
                raise ConfirmationError("unknown pending_id")
            if current["status"] in TERMINAL_STATES:
                return dict(current)
            if self._now() < datetime.fromisoformat(current["expires_at"]):
                raise ConfirmationError("pending request has not expired")
            return self._transition(pending_id, "expired", self._now(), "ttl")

    def route_without_confirmation(
        self,
        pending_id: str,
        mode: str,
        transport: Callable[[dict[str, str]], Any] | None = None,
        authorization: Authorization | None = None,
    ) -> dict[str, Any]:
        """Model scheduler and retry routes that must preserve the barrier.

        Before: pending_id exists and mode is a supported host scheduler route.
        During: every route uses attempt_delivery when a transport is supplied.
        After: pending routes return not_confirmed without touching transport.
        """
        if mode not in VALID_MODES:
            raise ConfirmationError("invalid delivery mode")
        if transport is not None:
            return self.attempt_delivery(pending_id, transport, authorization)
        with self._lock:
            current = self._latest(self._read(), pending_id)
            if current is None:
                raise ConfirmationError("unknown pending_id")
            return dict(current)

    def force_reactivate(
        self,
        *,
        target_thread_id: str,
        authorization: Authorization | None,
        reason: str,
        pending_id: str | None = None,
    ) -> dict[str, Any]:
        """Record a separate authenticated forced reactivation request.

        Before: a caller supplies a target, verifiable authorization, and
            non-empty reason; pending_id may identify delivery_unknown state.
        During: authorization is verified and either the unknown state is
            resolved or an audit entry is appended atomically.
        After: an audit response is returned, or a named rejection is returned.
        """
        if not reason.strip():
            return {"status": "error", "error": "reason_required"}
        auth_error = self._authorize(authorization)
        if auth_error is not None:
            return {"status": "error", "error": auth_error}
        now = self._now()
        evidence_digest = hashlib.sha256(
            authorization.token.encode("utf-8")
        ).hexdigest()
        if pending_id is not None:
            with self._lock:
                entries = self._read()
                current = self._latest(entries, pending_id)
                if current is None:
                    return {"status": "error", "error": "unknown_pending_id"}
                if current["status"] != "delivery_unknown":
                    return {"status": "error", "error": "not_delivery_unknown"}
                transition = {
                    **current,
                    "status": "reactivated",
                    "reactivated_at": _iso(now),
                    "actor": authorization.actor,
                    "evidence_digest": evidence_digest,
                    "reason": reason,
                }
                audit = {
                    "kind": "audit",
                    "event": "force_reactivate",
                    "pending_id": pending_id,
                    "actor": authorization.actor,
                    "reason": reason,
                    "evidence_digest": evidence_digest,
                    "at": _iso(now),
                }
                self._write([*entries, transition, audit])
            return {
                "status": "reactivated",
                "pending_id": pending_id,
                "target_thread_id": target_thread_id,
                "reason": reason,
            }
        audit = {
            "kind": "audit",
            "event": "force_reactivate",
            "actor": authorization.actor,
            "target_thread_id": target_thread_id,
            "reason": reason,
            "evidence_digest": evidence_digest,
            "at": _iso(now),
        }
        with self._lock:
            self._write([*self._read(), audit])
        return {
            "status": "reactivated",
            "target_thread_id": target_thread_id,
            "reason": reason,
        }

    def audit(self) -> list[dict[str, Any]]:
        """Return durable audit entries for inspection.

        Before: the store may contain confirmation and reactivation records.
        During: all JSONL entries are read without changing state.
        After: audit records are returned in durable order.
        """
        with self._lock:
            return [entry for entry in self._read() if entry.get("kind") == "audit"]
