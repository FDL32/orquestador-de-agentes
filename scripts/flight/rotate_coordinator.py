"""Fail-closed, versioned coordinator rotation for WOT-2026-153z.

The command is deliberately a thin policy gate around the existing roster
writer.  A chain authorization is revalidated from the real message store,
then consumed by a separate append-only ledger before phase A is allowed;
phase B only activates the identity installed by phase A and never consumes
another step.  ACK absence or staleness is rejected without mutation; the
executor owns restoring a phase-A backup when its measured deadline expires.
``--rehearsal`` copies every mutable flight file to a temporary directory and
never writes the real flight.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import flight_roster_writer as roster_writer  # noqa: E402
from scripts.flight import comms_alert  # noqa: E402
from scripts.flight.verify_user_authorization import (  # noqa: E402
    ChainAuthorityLedger,
    ChainAuthorizationRecord,
    Decision,
    check_schema,
    open_store_ro,
    revalidate_chain_authorization,
)


DEFAULT_FLIGHT = Path(
    "C:/Users/fdl/Proyectos_Python/orquestador_de_agentes_workspace/"
    ".agent/runtime/flight/vuelo-20261026b"
)
FILES = (
    "flight_roster.json",
    "session_registry.json",
    "roster_changes.jsonl",
    "autorizacion_cadena.json",
    "autorizacion_cadena.ledger.jsonl",
)
MIN_SEPARATION = timedelta(minutes=30)
MAX_CHAIN_STEPS = 12
HARD_QUOTA_PCT = 97
ACK_TIMEOUT_SECONDS = 900
UUID36 = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class RotationRejectedError(ValueError):
    """A policy or input condition rejected the rotation fail-closed."""


@dataclass(frozen=True)
class RotationRequest:
    out_code: str
    out_thread: str
    in_code: str
    in_thread: str
    slot: str
    package: str
    actor: str
    approved_by: str
    reason: str


def validate_approved_by(value: str) -> str:
    """Require the real user message UUID; defaults and prose are invalid."""
    if not isinstance(value, str) or UUID36.fullmatch(value) is None:
        raise RotationRejectedError("approved-by-message-id-form")
    return value


def load_chain_record(path: Path) -> ChainAuthorizationRecord:
    """Load and structurally validate the revalidatable chain snapshot."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RotationRejectedError("chain-authorization-unreadable") from exc
    if not isinstance(raw, dict):
        raise RotationRejectedError("chain-authorization-unreadable")
    try:
        return ChainAuthorizationRecord.from_mapping(raw)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RotationRejectedError(str(exc)) from exc


def _read_log(path: Path) -> list[dict[str, object]]:
    """Read the append-only rotation log without accepting malformed lines."""
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("rotation-log-line-not-object")
            rows.append(row)
    except (OSError, UnicodeError, ValueError) as exc:
        raise RotationRejectedError("rotation-log-corrupt") from exc
    return rows


def chain_consumption_count(log_path: Path, message_id: str) -> int:
    """Derive the safety counter from append-only roster changes."""
    return sum(
        1
        for row in _read_log(log_path)
        if row.get("change") == "chain_rotation_consumed"
        and row.get("messageId") == message_id
    )


def _last_chain_timestamp(log_path: Path, message_id: str) -> datetime | None:
    timestamps: list[datetime] = []
    for row in _read_log(log_path):
        if (
            row.get("change") != "chain_rotation_consumed"
            or row.get("messageId") != message_id
        ):
            continue
        value = row.get("ts")
        if not isinstance(value, str):
            raise RotationRejectedError("rotation-log-timestamp-invalid")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RotationRejectedError("rotation-log-timestamp-invalid") from exc
        if parsed.tzinfo is None:
            raise RotationRejectedError("rotation-log-timestamp-zone-required")
        timestamps.append(parsed)
    return max(timestamps) if timestamps else None


def _last_chain_in_code(log_path: Path, message_id: str) -> str:
    """Return the structured entrant for this authorization's latest phase A."""
    for row in reversed(_read_log(log_path)):
        if (
            row.get("change") != "chain_rotation_consumed"
            or row.get("messageId") != message_id
        ):
            continue
        in_code = row.get("inCode")
        if isinstance(in_code, str) and in_code:
            return in_code
        raise RotationRejectedError("phase-a-entrant-missing")
    raise RotationRejectedError("phase-a-missing")


def enforce_chain_policy(
    record: ChainAuthorizationRecord,
    *,
    log_path: Path,
    now: datetime,
    message_id: str,
    out_code: str | None = None,
    in_code: str | None = None,
) -> int:
    """Return the next ordinal only when every chain stop is closed safely."""
    if now.tzinfo is None:
        raise RotationRejectedError("now-zone-required")
    window_reason = record.validate_server_window()
    if window_reason:
        raise RotationRejectedError(f"chain-{window_reason}")
    if now.astimezone(timezone.utc) >= record.expires_at.astimezone(timezone.utc):
        raise RotationRejectedError("chain-expired")
    count = chain_consumption_count(log_path, message_id)
    if count >= MAX_CHAIN_STEPS:
        raise RotationRejectedError("chain-step-limit")
    if out_code is not None or in_code is not None:
        if isinstance(out_code, str) and isinstance(in_code, str):
            expected = tuple(record.successors[count : count + 2])
            pair_authorized = len(expected) == 2 and (out_code, in_code) == expected
        else:
            pair_authorized = False
        if not pair_authorized:
            raise RotationRejectedError("chain-pair-not-authorized")
    previous = _last_chain_timestamp(log_path, message_id)
    if (
        previous is not None
        and now.astimezone(timezone.utc) - previous.astimezone(timezone.utc)
        < MIN_SEPARATION
    ):
        raise RotationRejectedError("chain-separation-anomaly")
    return count + 1


def validate_rotation_preconditions(
    *,
    guard_rc: int,
    window_open: bool,
    quota_hard_pct: float,
    ack_age_seconds: float | None = None,
) -> None:
    """Reject an unmeasured guard, closed window, hard quota, or stale ACK."""
    if isinstance(guard_rc, bool) or not isinstance(guard_rc, int):
        raise RotationRejectedError("roster-guard-invalid")
    if not isinstance(window_open, bool):
        raise RotationRejectedError("rotation-window-invalid")
    if (
        isinstance(quota_hard_pct, bool)
        or not isinstance(quota_hard_pct, (int, float))
        or not math.isfinite(quota_hard_pct)
        or not 0 <= quota_hard_pct <= 100
    ):
        raise RotationRejectedError("quota-hard-invalid")
    if ack_age_seconds is not None and (
        isinstance(ack_age_seconds, bool)
        or not isinstance(ack_age_seconds, (int, float))
        or not math.isfinite(ack_age_seconds)
        or ack_age_seconds < 0
    ):
        raise RotationRejectedError("ack-age-invalid")
    if guard_rc != 0:
        raise RotationRejectedError("roster-guard-failed")
    if not window_open:
        raise RotationRejectedError("rotation-window-closed")
    if quota_hard_pct >= HARD_QUOTA_PCT:
        raise RotationRejectedError("quota-hard-stop")
    if ack_age_seconds is not None and ack_age_seconds > ACK_TIMEOUT_SECONDS:
        raise RotationRejectedError("ack-timeout")


def _append_rotation_log(
    path: Path,
    *,
    request: RotationRequest,
    message_id: str,
    step: int,
    now: datetime,
    literal_text: str,
) -> None:
    row = {
        "ts": now.astimezone(timezone.utc).isoformat(),
        "by": request.actor,
        "change": "chain_rotation_consumed",
        "detail": f"{request.out_code} -> {request.in_code}",
        "reason": request.reason,
        "literal_text": literal_text,
        "messageId": message_id,
        "step": step,
        "outCode": request.out_code,
        "inCode": request.in_code,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _snapshot_mutable_files(
    flight_dir: Path, *, extra: tuple[Path, ...] = ()
) -> dict[Path, bytes | None]:
    paths = tuple(flight_dir / name for name in FILES) + extra
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def _restore_mutable_files(snapshot: dict[Path, bytes | None]) -> None:
    for path, data in snapshot.items():
        if data is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(data)


def _mark_owned_files(owned: dict[Path, bytes | None], paths: tuple[Path, ...]) -> None:
    for path in paths:
        owned[path] = path.read_bytes() if path.exists() else None


def _run_owned_write(
    operation, owned: dict[Path, bytes | None], paths: tuple[Path, ...]
) -> None:
    try:
        operation()
    except Exception:
        _mark_owned_files(owned, paths)
        raise
    _mark_owned_files(owned, paths)


@contextlib.contextmanager
def _flight_exclusion(flight_dir: Path):
    lock_path = flight_dir / ".rotate_coordinator.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RotationRejectedError("rotation-concurrent") from exc
    try:
        os.close(fd)
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


def _rollback_mutable_files(
    snapshot: dict[Path, bytes | None], owned: dict[Path, bytes | None]
) -> None:
    conflicts: list[str] = []
    for path, original in snapshot.items():
        current = path.read_bytes() if path.exists() else None
        if current == original:
            continue
        expected = owned.get(path)
        if path in owned and current == expected:
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
            continue
        conflicts.append(path.name)
    if conflicts:
        names = ",".join(sorted(set(conflicts)))
        raise RotationRejectedError(f"rollback-conflict:{names}")


def _validate_phase_a_outgoing(flight_dir: Path, request: RotationRequest) -> None:
    try:
        roster = roster_writer._read_roster(flight_dir / "flight_roster.json")
        registry = _load_registry(flight_dir / "session_registry.json")
    except Exception as exc:
        raise RotationRejectedError("phase-a-outgoing-identity-mismatch") from exc
    active_roles = roster.get("active_roles")
    orchestrator = (
        active_roles.get("orquestador") if isinstance(active_roles, dict) else None
    )
    sessions = registry.get("sessions")
    outgoing_sessions = (
        [
            session
            for session in sessions
            if isinstance(session, dict) and session.get("code") == request.out_code
        ]
        if isinstance(sessions, list)
        else []
    )
    if (
        not isinstance(orchestrator, dict)
        or orchestrator.get("session_code") != request.out_code
        or orchestrator.get("threadId") != request.out_thread
        or registry.get("orquestador_activo") != request.out_code
        or len(outgoing_sessions) != 1
    ):
        raise RotationRejectedError("phase-a-outgoing-identity-mismatch")


def _load_registry(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RotationRejectedError("session-registry-unreadable") from exc
    if not isinstance(data, dict):
        raise RotationRejectedError("session-registry-invalid")
    return data


def _save_registry(path: Path, data: dict[str, object]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _rotate_registry(path: Path, request: RotationRequest, timestamp: str) -> None:
    registry = _load_registry(path)
    sessions = registry.get("sessions")
    if not isinstance(sessions, list):
        raise RotationRejectedError("session-registry-sessions-invalid")
    for session in sessions:
        if not isinstance(session, dict):
            raise RotationRejectedError("session-registry-session-invalid")
        if session.get("code") == request.out_code:
            session["role"] = "supervisora"
            session["status"] = f"SUPERVISORA directa de {request.in_code}"
    if any(isinstance(s, dict) and s.get("code") == request.in_code for s in sessions):
        raise RotationRejectedError("incoming-session-already-registered")
    sessions.append(
        {
            "code": request.in_code,
            "role": "orquestadora",
            "slot": request.slot,
            "threadId": request.in_thread,
            "started": timestamp,
            "status": "ACTIVA (PENDIENTE_ACK)",
            "supersedes": request.out_code,
            "launched_by": request.out_code,
            "nota": request.package,
        }
    )
    registry["orquestador_activo"] = request.in_code
    registry["actualizado"] = timestamp
    _save_registry(path, registry)


def _install_incoming_orchestrator(
    roster_path: Path,
    request: RotationRequest,
    *,
    message_id: str,
    now: datetime,
    changes_log_path: Path,
) -> None:
    """Install the incoming orchestrator identity before supervisor rotation."""
    current = roster_writer._read_roster(roster_path)
    active_roles = current.get("active_roles")
    if not isinstance(active_roles, dict):
        raise RotationRejectedError("roster-active-roles-invalid")
    current_orchestrator = active_roles.get("orquestador")
    if not isinstance(current_orchestrator, dict):
        raise RotationRejectedError("roster-orchestrador-invalid")
    if current_orchestrator.get("estado") != "PENDIENTE_ACK":
        raise RotationRejectedError("phase-a-orchestrator-not-pending")
    version = current_orchestrator.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise RotationRejectedError("roster-orchestrator-version-invalid")
    incoming = {
        "threadId": request.in_thread,
        "session_code": request.in_code,
        "since": now.isoformat(),
        "set_by": request.actor,
        "predecessor_threadId": request.out_thread,
        "version": version + 1,
        "status": "active",
        "approved_by": message_id,
        "nota": request.package,
        "estado": "PENDIENTE_ACK",
    }
    roster_writer._validate_active_role_fields(incoming)
    updated = json.loads(json.dumps(current, ensure_ascii=False))
    updated["active_roles"]["orquestador"] = incoming
    roster_writer._atomic_write_json(roster_path, updated)
    roster_writer._append_change_line(
        changes_log_path,
        by=request.actor,
        change="orquestador_rotation",
        detail=(
            f"orquestador {request.out_thread} -> {request.in_thread} "
            f"({request.in_code}); estado PENDIENTE_ACK; "
            f"version {version} -> {version + 1}"
        ),
        reason=request.reason,
    )


def _rotate_phase_a_locked(
    flight_dir: Path,
    request: RotationRequest,
    *,
    message_id: str,
    now: datetime,
    decision: Decision,
    guard_rc: int,
    window_open: bool,
    quota_hard_pct: float,
    record: ChainAuthorizationRecord | None,
) -> int:
    """Consume the revalidated record and perform phase-A changes atomically.

    Before: ``record`` is the immutable authorization object revalidated by
        ``main``; it must be present and its ``message_id`` must equal
        ``message_id``. Missing or mismatched records are rejected with
        ``chain-record-required`` or ``chain-record-message-mismatch``.
    During: the record is compared with the on-disk snapshot inside the
        per-flight exclusion before policy enforcement or ledger consumption.
    After: phase A consumes only that record and restores caught writes; a
        changed on-disk record is rejected as ``chain-record-changed``.

    The snapshot restores mutable files, ledger, and lock when an exception is
    caught.  It cannot restore state after process termination between writes;
    the executor owns that recovery through its ``pre_rotate`` backups, using
    the exact procedure in ``docs/protocol/flight_supervision.md``.
    """
    validate_approved_by(request.approved_by)
    if (
        not decision.allowed
        or decision.message_id != message_id
        or request.approved_by != message_id
    ):
        raise RotationRejectedError("chain-revalidation-rejected")
    validate_rotation_preconditions(
        guard_rc=guard_rc,
        window_open=window_open,
        quota_hard_pct=quota_hard_pct,
    )
    if record is None:
        raise RotationRejectedError("chain-record-required")
    if record.message_id != message_id:
        raise RotationRejectedError("chain-record-message-mismatch")
    current_record = load_chain_record(flight_dir / "autorizacion_cadena.json")
    if current_record != record:
        raise RotationRejectedError("chain-record-changed")
    step = enforce_chain_policy(
        record,
        log_path=flight_dir / "roster_changes.jsonl",
        now=now,
        message_id=message_id,
        out_code=request.out_code,
        in_code=request.in_code,
    )
    ledger = ChainAuthorityLedger(flight_dir / "autorizacion_cadena.ledger.jsonl")
    lock_path = ledger._lock_path(message_id, step)
    roster_path = flight_dir / "flight_roster.json"
    log_path = flight_dir / "roster_changes.jsonl"
    _validate_phase_a_outgoing(flight_dir, request)
    snapshot = _snapshot_mutable_files(flight_dir, extra=(lock_path,))
    owned: dict[Path, bytes | None] = {}
    try:
        consumed = ledger.consume(message_id, step, request.out_code, request.in_code)
    except Exception:
        _mark_owned_files(owned, (ledger.path, lock_path))
        _rollback_mutable_files(snapshot, owned)
        raise
    if not consumed:
        raise RotationRejectedError("chain-step-consumed")
    _mark_owned_files(owned, (ledger.path, lock_path))
    try:
        _run_owned_write(
            lambda: roster_writer.write_role_estado(
                roster_path,
                "orquestador",
                "PENDIENTE_ACK",
                changes_log_path=log_path,
                actor=request.actor,
                reason=request.reason,
            ),
            owned,
            (roster_path, log_path),
        )
        _run_owned_write(
            lambda: _install_incoming_orchestrator(
                roster_path,
                request,
                message_id=message_id,
                now=now,
                changes_log_path=log_path,
            ),
            owned,
            (roster_path, log_path),
        )
        _run_owned_write(
            lambda: _rotate_registry(
                flight_dir / "session_registry.json", request, now.isoformat()
            ),
            owned,
            (flight_dir / "session_registry.json",),
        )
        _run_owned_write(
            lambda: roster_writer.write_supervisor(
                roster_path,
                request.out_thread,
                request.out_code,
                changes_log_path=log_path,
                actor=request.actor,
                reason=request.reason,
            ),
            owned,
            (roster_path, log_path),
        )
        _run_owned_write(
            lambda: _append_rotation_log(
                log_path,
                request=request,
                message_id=message_id,
                step=step,
                now=now,
                literal_text=record.literal_text,
            ),
            owned,
            (log_path,),
        )
    except Exception:
        _rollback_mutable_files(snapshot, owned)
        raise
    return step


def rotate_phase_a(
    flight_dir: Path,
    request: RotationRequest,
    *,
    message_id: str,
    now: datetime,
    decision: Decision,
    guard_rc: int,
    window_open: bool,
    quota_hard_pct: float,
    record: ChainAuthorizationRecord | None = None,
) -> int:
    """Run phase A with the required record revalidated by ``main``.

    Before: the flight files, verified request, and revalidated ``record`` are
        ready; ``record=None`` is rejected with ``chain-record-required``.
    During: holds the per-flight exclusion and verifies message identity and
        on-disk equality before consuming the record.
    After: returns the step or restores owned changes; invalid authorization
        bindings use stable chain-record rejection reasons.
    """
    with _flight_exclusion(flight_dir):
        return _rotate_phase_a_locked(
            flight_dir,
            request,
            message_id=message_id,
            now=now,
            decision=decision,
            guard_rc=guard_rc,
            window_open=window_open,
            quota_hard_pct=quota_hard_pct,
            record=record,
        )


def _rotate_phase_b_locked(
    flight_dir: Path,
    request: RotationRequest,
    *,
    decision: Decision,
    guard_rc: int,
    window_open: bool,
    quota_hard_pct: float,
    ack_age_seconds: float,
) -> None:
    """Activate phase A's entrant after a valid, measured ACK.

    The snapshot restores mutable files when an exception is caught.  It does
    not cover process termination between writes; the executor owns recovery
    from its ``pre_rotate`` backups.
    """
    if not decision.allowed or decision.message_id != request.approved_by:
        raise RotationRejectedError("chain-revalidation-rejected")
    if ack_age_seconds is None:
        raise RotationRejectedError("ack-unmeasured")
    validate_rotation_preconditions(
        guard_rc=guard_rc,
        window_open=window_open,
        quota_hard_pct=quota_hard_pct,
        ack_age_seconds=ack_age_seconds,
    )
    roster_path = flight_dir / "flight_roster.json"
    log_path = flight_dir / "roster_changes.jsonl"
    roster = roster_writer._read_roster(roster_path)
    active_roles = roster.get("active_roles")
    orquestador = (
        active_roles.get("orquestador") if isinstance(active_roles, dict) else None
    )
    if (
        not isinstance(orquestador, dict)
        or orquestador.get("estado") != "PENDIENTE_ACK"
    ):
        raise RotationRejectedError("phase-a-required")
    phase_a_code = _last_chain_in_code(log_path, decision.message_id)
    if phase_a_code != request.in_code:
        raise RotationRejectedError("phase-a-entrant-mismatch")
    if (
        orquestador.get("session_code") != request.in_code
        or orquestador.get("threadId") != request.in_thread
    ):
        raise RotationRejectedError("phase-a-identity-mismatch")
    if orquestador.get("approved_by") != decision.message_id:
        raise RotationRejectedError("phase-a-authorization-mismatch")
    registry = _load_registry(flight_dir / "session_registry.json")
    sessions = registry.get("sessions")
    if not isinstance(sessions, list):
        raise RotationRejectedError("session-registry-sessions-invalid")
    matching_sessions = [
        session
        for session in sessions
        if isinstance(session, dict) and session.get("code") == request.in_code
    ]
    if (
        registry.get("orquestador_activo") != request.in_code
        or len(matching_sessions) != 1
    ):
        raise RotationRejectedError("session-registry-identity-mismatch")
    snapshot = _snapshot_mutable_files(flight_dir)
    owned: dict[Path, bytes | None] = {}
    try:
        _run_owned_write(
            lambda: roster_writer.write_role_estado(
                roster_path,
                "orquestador",
                "ACTIVO",
                changes_log_path=log_path,
                actor=request.actor,
                reason=f"ACK recibido de {request.in_code}; {request.reason}",
            ),
            owned,
            (roster_path, log_path),
        )
        matching_sessions[0]["status"] = "ACTIVA (ACK recibido)"
        _run_owned_write(
            lambda: _save_registry(flight_dir / "session_registry.json", registry),
            owned,
            (flight_dir / "session_registry.json",),
        )
    except Exception:
        _rollback_mutable_files(snapshot, owned)
        raise


def rotate_phase_b(
    flight_dir: Path,
    request: RotationRequest,
    *,
    decision: Decision,
    guard_rc: int,
    window_open: bool,
    quota_hard_pct: float,
    ack_age_seconds: float,
) -> None:
    """Run phase B under the same per-flight exclusion and rollback journal."""
    with _flight_exclusion(flight_dir):
        return _rotate_phase_b_locked(
            flight_dir,
            request,
            decision=decision,
            guard_rc=guard_rc,
            window_open=window_open,
            quota_hard_pct=quota_hard_pct,
            ack_age_seconds=ack_age_seconds,
        )


def revalidate_from_store(
    record: ChainAuthorizationRecord,
    *,
    store_path: Path,
    anchor_message_id: str,
    now: datetime,
) -> Decision:
    """Revalidate the real message through the shared read-only verifier."""
    connection = open_store_ro(store_path)
    try:
        check_schema(connection)
        return revalidate_chain_authorization(
            connection,
            record=record,
            anchor_message_id=anchor_message_id,
            now=now,
        )
    finally:
        connection.close()


def _copy_rehearsal(flight_dir: Path) -> tuple[Path, Path]:
    temp_root = Path(tempfile.mkdtemp(prefix="rotate_coordinator_"))
    rehearsal = temp_root / "flight"
    rehearsal.mkdir()
    for name in FILES:
        source = flight_dir / name
        if source.exists():
            shutil.copy2(source, rehearsal / name)
        elif name.endswith(".jsonl"):
            (rehearsal / name).write_text("", encoding="utf-8")
        else:
            raise RotationRejectedError(f"rehearsal-missing-{name}")
    return rehearsal, temp_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fl-dir", type=Path, default=DEFAULT_FLIGHT)
    parser.add_argument("--out-code", required=True)
    parser.add_argument("--out-thread", required=True)
    parser.add_argument("--in-code", required=True)
    parser.add_argument("--in-thread", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--anchor-message-id", required=True)
    parser.add_argument("--store-path", type=Path, required=True)
    parser.add_argument("--ops-dir", type=Path)
    parser.add_argument("--guard-rc", type=int, required=True)
    parser.add_argument("--window-state", choices=("open", "closed"), required=True)
    parser.add_argument("--quota-hard-pct", type=float, required=True)
    parser.add_argument("--ack-age-seconds", type=float)
    parser.add_argument("--apply-phase", choices=("A", "B"))
    parser.add_argument("--rehearsal", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    request = RotationRequest(
        args.out_code,
        args.out_thread,
        args.in_code,
        args.in_thread,
        args.slot,
        args.package,
        args.actor,
        args.approved_by,
        args.reason,
    )
    now = datetime.now(timezone.utc)
    target = args.fl_dir
    temp_root: Path | None = None
    try:
        validate_approved_by(args.approved_by)
        if args.rehearsal:
            target, temp_root = _copy_rehearsal(args.fl_dir)
        record = load_chain_record(target / "autorizacion_cadena.json")
        decision = revalidate_from_store(
            record,
            store_path=args.store_path,
            anchor_message_id=args.anchor_message_id,
            now=now,
        )
        if args.apply_phase == "A":
            rotate_phase_a(
                target,
                request,
                message_id=args.message_id,
                now=now,
                decision=decision,
                guard_rc=args.guard_rc,
                window_open=args.window_state == "open",
                quota_hard_pct=args.quota_hard_pct,
                record=record,
            )
        elif args.apply_phase == "B":
            rotate_phase_b(
                target,
                request,
                decision=decision,
                guard_rc=args.guard_rc,
                window_open=args.window_state == "open",
                quota_hard_pct=args.quota_hard_pct,
                ack_age_seconds=args.ack_age_seconds,
            )
        else:
            raise RotationRejectedError("phase-required")
        print(f"OK phase={args.apply_phase} rehearsal={args.rehearsal}")
        if temp_root is not None:
            print(f"rehearsal-root={temp_root}")
        return 0
    except (KeyError, RotationRejectedError, OSError, ValueError) as exc:
        if (
            isinstance(exc, RotationRejectedError)
            and str(exc) == "chain-separation-anomaly"
        ):
            try:
                comms_alert.configure(args.ops_dir)
                alert_rc = comms_alert.event(
                    "relevo-separacion",
                    "URGENTE",
                    None,
                    "Parada urgente: separación mínima entre relevos violada",
                    False,
                    False,
                    owner="rotate",
                    session_code=request.in_code,
                )
                print(f"URGENTE relevo-separacion rc_aviso={alert_rc}")
            except Exception as alert_exc:
                print(f"URGENTE relevo-separacion rc_aviso=2: {alert_exc}")
        print(f"REJECTED: {exc}")
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
