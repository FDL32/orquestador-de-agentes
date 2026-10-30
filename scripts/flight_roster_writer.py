#!/usr/bin/env python3
"""Atomic flight roster writer for role state transitions.

Writes per-role active_roles.<rol>.estado (ACTIVO/PENDIENTE_ACK/SALIENTE_MUERTO)
with version CAS on read, single retry on conflict, round-trip identity
validation before replace, and canonical log line append.

Also seeds authority and session_relief schema blocks idempotently.

CLI thin wrapper (main) maps exceptions to exit codes: 0=ok, 2=conflict,
3=validation error.

Contract (Before/During/After):

Before: roster_path and changes_log_path are valid file paths (files may
    not yet exist for the first call).  actor and reason are non-empty strings.

During: read the roster JSON once outside the retry loop (first attempt) or
    re-read before attempt 1 (retry).  Validate the requested transition
    against TRANSICIONES_VALIDAS.  Build a deep-copy new_roster with the
    new estado and incremented version.  Immediately re-read to check
    version CAS; if mismatched, log write_conflict and retry once (attempt 0)
    or raise RosterWriteConflict (attempt 1).  Validate round-trip
    identity via _assert_roundtrip_identical (inside _atomic_write_json).
    Write atomically via tempfile + fsync + os.replace.  Append a canonical
    change line to changes_log_path.

After: returns the new roster dict on success.  The roster file on disk
    reflects the new state with an incremented version.  One new canonical
    line (ts/by/change/detail/reason) is appended to changes_log_path.
    RosterWriteConflict is raised on CAS mismatch after the single retry.
    RosterInvalidTransition is raised for invalid state transitions.
    RosterUnknownField is raised for unknown role or unknown entry fields.
    RosterRoundTripError is raised if the new roster cannot survive a
    JSON round-trip (json.loads(json.dumps(...)) != original).
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


# --- Dual import support for guard helper ---
# Insert motor root so `from scripts.x import` works when run as script.
# Then try scripts. prefix first, fall back to direct import.
_MOTOR_ROOT = Path(__file__).resolve().parent.parent
if str(_MOTOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_MOTOR_ROOT))

_supervisor_esperado = None
try:
    from scripts.check_roster_matches_acting_thread import (
        supervisor_esperado as _supervisor_esperado,
    )
except ImportError:
    try:
        from check_roster_matches_acting_thread import (
            supervisor_esperado as _supervisor_esperado,  # type: ignore[no-redef]
        )
    except ImportError:
        _supervisor_esperado = None


# --- Constants ---

ESTADOS_VALIDOS = {"ACTIVO", "PENDIENTE_ACK", "SALIENTE_MUERTO"}

TRANSICIONES_VALIDAS: frozenset[tuple[str, str]] = frozenset(
    {
        ("ACTIVO", "PENDIENTE_ACK"),
        ("PENDIENTE_ACK", "ACTIVO"),
        ("PENDIENTE_ACK", "SALIENTE_MUERTO"),
    }
)

ESTADO_IMPLICITO_SIN_CAMPO = "ACTIVO"

# Valid keys for an active_roles entry.  Any key outside this set is
# RosterUnknownField.  "estado" is the NEW field; existing entries may not
# carry it yet (implicit ACTIVO).
_ACTIVE_ROLE_KEYS: frozenset[str] = frozenset(
    {
        "threadId",
        "session_code",
        "since",
        "set_by",
        "predecessor_threadId",
        "version",
        "status",
        "approved_by",
        "nota",
        "estado",
    }
)


# --- Exceptions ---


class RosterWriteConflict(Exception):  # noqa: N818
    """CAS mismatch on both attempt 0 and attempt 1."""


class RosterInvalidTransition(Exception):  # noqa: N818
    """Requested estado transition is not in TRANSICIONES_VALIDAS."""


class RosterUnknownField(Exception):  # noqa: N818
    """Role name or entry field is not known to the roster schema."""


class RosterRoundTripError(Exception):
    """New roster data does not survive a JSON round-trip identically."""


class RosterInvalidSupervisor(Exception):  # noqa: N818
    """Supervisor identity or transition validation failed."""


class RosterMalformed(Exception):  # noqa: N818
    """Roster file is unreadable or its shape is invalid (fail closed)."""


# --- Private helpers ---


def _read_roster(path: Path | str) -> dict[str, Any]:
    """Read and parse roster JSON.

    Before: path points to a valid JSON file whose top level is a mapping.
    During: reads the file with utf-8 encoding and parses JSON.
    After: returns the top-level dict.  Raises RosterMalformed when the file
        cannot be read, is not valid JSON/UTF-8, or its top level is not a mapping.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RosterMalformed(f"roster ilegible: {exc}") from exc
    if not isinstance(data, dict):
        raise RosterMalformed("el nivel superior del roster no es un mapping")
    return data


def _role_entry(state: dict[str, Any], role: str) -> dict[str, Any]:
    """Return active_roles[role] after checking the shape it relies on.

    Before: state is a roster mapping; role is the requested role name.
    During: checks that active_roles and the role entry are mappings and that
        the role entry carries an int version.  No I/O.
    After: returns the role entry.  Raises RosterUnknownField for an unknown
        role and RosterMalformed for any shape problem.
    """
    ar = state.get("active_roles")
    if not isinstance(ar, dict):
        raise RosterMalformed("active_roles no es un mapping")
    if role not in ar or role == "_schema_note":
        raise RosterUnknownField(f"rol desconocido: {role}")
    entry = ar[role]
    if not isinstance(entry, dict):
        raise RosterMalformed(f"active_roles.{role} no es un mapping")
    if not isinstance(entry.get("version"), int):
        raise RosterMalformed(f"active_roles.{role}.version debe ser int")
    return entry


def _assert_roundtrip_identical(data: Any) -> None:
    """Verify that `data` survives a JSON round-trip identically.

    Before: `data` is a dict (or other serialisable structure).
    During: serialises with ensure_ascii=False, re-parses, and compares
        with != (not ==, because tuple->[list] conversion makes round-trip
        data strictly *different* for tuples).
    After: raises RosterRoundTripError if roundtrip != data.
    """
    roundtrip = json.loads(json.dumps(data, ensure_ascii=False))
    if roundtrip != data:
        raise RosterRoundTripError(
            "el roster nuevo no sobrevive un round-trip JSON identico"
        )


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write-tmp-then-rename with round-trip check and fsync.

    Before: path.parent exists and is writable.  data is round-trip safe
        (checked before calling).
    During: serialises to a NamedTemporaryFile in the same directory,
        flushes, fsyncs, then os.replaces the old file.  If anything
        fails, the temp file is cleaned up and the original destination
        is never modified.
    After: the destination file contains the new JSON (or does not exist
        if an earlier error occurred).
    """
    _assert_roundtrip_identical(data)
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=str(path.parent),
            prefix=f"{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(path))
    except BaseException:
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        raise


def _now_iso() -> str:
    """Current time as ISO 8601 string with seconds precision."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _append_change_line(
    changes_log_path: Path | str,
    *,
    by: str,
    change: str,
    detail: str,
    reason: str,
) -> None:
    """Append a canonical change line to the roster_changes.jsonl log.

    Before: changes_log_path may or may not exist.  If it exists, its last
        byte may or may not be a newline.
    During: if the file exists, is non-empty, and its last byte is not
        b"\\n", appends b"\\n" via append mode.  Then appends the new JSON
        line with the current system clock timestamp.
    After: one new line is appended (never a rewrite of the file).  The
        new line uses the canonical schema ts/by/change/detail/reason.
    """
    p = Path(changes_log_path)
    if p.exists() and p.stat().st_size > 0:
        with open(p, "rb") as f:
            f.seek(-1, 2)  # last byte
            last_byte = f.read(1)
        if last_byte != b"\n":
            # Append a leading newline in append-binary mode to never truncate.
            with open(p, "ab") as f:
                f.write(b"\n")
    line = json.dumps(
        {
            "ts": _now_iso(),
            "by": by,
            "change": change,
            "detail": detail,
            "reason": reason,
        },
        ensure_ascii=False,
    )
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        f.write(line + "\n")


def _validate_active_role_fields(entry: dict[str, Any]) -> None:
    """Raise RosterUnknownField if `entry` has keys outside the valid set.

    Before: `entry` is a dict representing one active_roles item.
    During: checks every key against _ACTIVE_ROLE_KEYS.
    After: raises RosterUnknownField if an unexpected key is found.
    """
    for key in entry:
        if key not in _ACTIVE_ROLE_KEYS:
            raise RosterUnknownField(f"campo desconocido en active_roles.{key}")


def _validate_old_estado(old_estado: str | None) -> None:
    """Raise RosterInvalidTransition if old_estado is present but unrecognized.

    Before: old_estado is None (absent -> implicit ACTIVO) or a string.
    During: if old_estado is not None and not in ESTADOS_VALIDOS, this is
        a present-but-unrecognized value (corruption, typo, empty string)
        and must fail closed -- it must NEVER be silently treated as ACTIVO.
    After: raises RosterInvalidTransition if old_estado is present and
        unrecognized.  No-op otherwise.
    """
    if old_estado is not None and old_estado not in ESTADOS_VALIDOS:
        raise RosterInvalidTransition(
            f"estado existente no reconocido: {old_estado!r} "
            f"(esperado uno de {ESTADOS_VALIDOS} o ausente)"
        )


def _validate_transition(old_estado: str | None, new_estado: str) -> None:
    """Validate the transition (old -> new).

    Before: old_estado may be None (implicit ACTIVO).  new_estado must be
        one of ESTADOS_VALIDOS.
    During: validates that old_estado is present and recognized (fail-closed).
        Then if new_estado == old (or ESTADO_IMPLICITO_SIN_CAMPO when old
        is None), this is a no-op -- no exception is raised and the caller
        should skip writing.  Otherwise, checks against TRANSICIONES_VALIDAS.
    After: raises RosterInvalidTransition if the transition is not allowed.
    """
    _validate_old_estado(old_estado)
    effective_old = old_estado or ESTADO_IMPLICITO_SIN_CAMPO
    if new_estado not in ESTADOS_VALIDOS:
        raise RosterInvalidTransition(
            f"estado no valido: {new_estado!r} (esperado uno de {ESTADOS_VALIDOS})"
        )
    if (effective_old, new_estado) not in TRANSICIONES_VALIDAS:
        raise RosterInvalidTransition(
            f"transicion invalida: {effective_old!r} -> {new_estado!r}"
        )


# --- Public API ---


def write_role_estado(
    roster_path: Path | str,
    role: str,
    new_estado: str,
    *,
    changes_log_path: Path | str,
    actor: str,
    reason: str,
    ts: str | None = None,
) -> dict[str, Any]:
    """Write a per-role estado transition with CAS retry and round-trip check.

    Before: roster_path points to a valid JSON roster file.  role is a key
        under active_roles.  new_estado is one of ESTADOS_VALIDOS.

    During: if ts is not None, raises ValueError immediately (before
        reading anything).  Validates the role exists in active_roles.
        Determines old_estado (implicit ACTIVO if absent).  If the new
        estado equals the old, returns immediately (no-op -- no file
        write, no version bump, no log line).  Otherwise, attempts up to
        2 CAS operations: attempt 0 reuses the initial read; attempt 1
        re-reads the base.  On each attempt, re-reads immediately before
        write; if version changed, logs write_conflict.  On attempt 1
        mismatch, raises RosterWriteConflict without writing.  On success,
        writes atomically (with round-trip check) and appends a canonical
        change line.

    After: returns the new roster dict.  The roster file reflects the new
        state with incremented version.  One canonical log line is appended.
        Raises RosterWriteConflict on CAS mismatch after the single retry.
        Raises RosterInvalidTransition for disallowed transitions.
        Raises RosterUnknownField for unknown role.  Raises RosterRoundTripError
        if the new roster cannot survive a JSON round-trip.
    """
    # Reject explicit ts immediately -- ts must always be stamped by the clock.
    if ts is not None:
        raise ValueError(
            "ts por argumento no es valido; el ts se estampa siempre con el reloj"
        )

    current: dict[str, Any] = _read_roster(roster_path)

    # Validate role exists in active_roles and the shape it relies on.
    old_estado: str | None = _role_entry(current, role).get("estado")

    # Validate old_estado is present and recognized (fail-closed).
    _validate_old_estado(old_estado)

    # No-op: new estado equals the current (with implicit ACTIVO).
    effective_old = old_estado or ESTADO_IMPLICITO_SIN_CAMPO
    if new_estado == effective_old:
        return current

    # Attempt up to 2 CAS operations.
    for attempt in (0, 1):
        if attempt == 1:
            current = _read_roster(roster_path)

        current_entry = _role_entry(current, role)
        seen_version = current_entry["version"]

        # Validate transition against the state read in this attempt.
        current_old = current_entry.get("estado")

        # Validate old_estado is present and recognized (fail-closed),
        # even on the retry re-read.
        _validate_old_estado(current_old)

        # No-op: the concurrent writer already achieved the same transition.
        current_effective_old = current_old or ESTADO_IMPLICITO_SIN_CAMPO
        if new_estado == current_effective_old:
            return current

        _validate_transition(current_old, new_estado)

        # Build new roster (deep copy to avoid mutating shared state).
        new_roster = copy.deepcopy(current)
        new_roster["active_roles"][role]["estado"] = new_estado
        new_roster["active_roles"][role]["version"] = seen_version + 1

        # Validate active_roles fields.
        _validate_active_role_fields(new_roster["active_roles"][role])

        # CAS: re-read immediately before writing.
        fresh = _read_roster(roster_path)
        fresh_version = _role_entry(fresh, role)["version"]
        if fresh_version != seen_version:
            _append_change_line(
                changes_log_path,
                by=actor,
                change="write_conflict",
                detail=(
                    f"role={role} intento={attempt} "
                    f"version_esperada={seen_version} "
                    f"version_real={fresh_version}"
                ),
                reason=reason,
            )
            if attempt == 1:
                raise RosterWriteConflict(
                    f"conflicto de escritura para {role} "
                    f"(intento {attempt}: version_esperada={seen_version}, "
                    f"version_real={fresh_version})"
                )
            if attempt == 0:
                continue

        # No conflict: write atomically.
        _atomic_write_json(roster_path, new_roster)

        _append_change_line(
            changes_log_path,
            by=actor,
            change="estado_transition",
            detail=f"role={role} {effective_old} -> {new_estado}",
            reason=reason,
        )
        return new_roster

    # Should not reach here, but guard anyway.
    raise RosterWriteConflict(f"conflicto de escritura para {role} tras {2} intentos")


def _validate_supervisor_fields(entry: dict[str, Any]) -> None:
    """Raise RosterInvalidSupervisor if required supervisor fields are missing or wrong type.

    Before: `entry` is a dict representing one active_roles supervisor item.
    During: checks presence and type of threadId (str), session_code (str), version (int).
    After: raises RosterInvalidSupervisor if any field is missing or wrong type.
    """
    for key in ("threadId", "session_code"):
        val = entry.get(key)
        if not isinstance(val, str) or not val:
            raise RosterInvalidSupervisor(
                f"campo requerido '{key}' debe ser string no vacio, got {val!r}"
            )
    version = entry.get("version")
    if not isinstance(version, int):
        raise RosterInvalidSupervisor(
            f"campo requerido 'version' debe ser int, got {version!r}"
        )


def _validate_rotation(  # noqa: C901
    state: dict[str, Any],
    supervisor_thread_id: str,
    supervisor_session_code: str,
    excepcion: str | None,
) -> bool:
    """Validate a supervisor rotation against one roster state (closed failures).

    Before: `state` is a roster dict freshly read from disk; `excepcion` is
        already normalized (None when empty).
    During: checks that active_roles, supervisor and orquestador are mappings and
        the supervisor field types.  Then, if the requested supervisor is already
        the active one, returns at once (the no-op wins over every rule below,
        even over corrupt data).  Otherwise checks supervisor != orquestador,
        cadena_contexto shape, orquestador and requested supervisor absent from
        it, mcp: prefix, non-empty session_code, orquestador version int, and
        the rule predecessor-xor-excepcion.  No I/O.
    After: returns True for the no-op (nothing is written); returns False when
        the rotation is valid; raises RosterInvalidSupervisor on any closed failure.
    """
    ar = state.get("active_roles")
    if not isinstance(ar, dict):
        raise RosterInvalidSupervisor("active_roles no es un mapping")

    sup = ar.get("supervisor")
    if not isinstance(sup, dict):
        raise RosterInvalidSupervisor("active_roles.supervisor no es un mapping")

    orq = ar.get("orquestador")
    if not isinstance(orq, dict):
        raise RosterInvalidSupervisor("active_roles.orquestador no es un mapping")

    _validate_supervisor_fields(sup)

    # No-op WINS (plan DoD 2): the requested supervisor is already the active one,
    # so nothing is written even if the rest of the data is corrupt.  The checks
    # below guard a rotation; they do not apply to an idempotent call.
    if supervisor_thread_id == sup.get("threadId", ""):
        return True

    orq_thread = orq.get("threadId")
    if supervisor_thread_id == orq_thread:
        raise RosterInvalidSupervisor(
            "el nuevo supervisor no puede ser el orquestador activo"
        )

    # cadena_contexto: null is the same as absent; anything else must be a list
    # of mappings that carry a threadId (the guard rejects the same shapes).
    cascada = state.get("cadena_contexto")
    if cascada is None:
        cascada = []
    if not isinstance(cascada, list):
        raise RosterInvalidSupervisor("cadena_contexto presente pero no es una lista")
    for entry in cascada:
        if not isinstance(entry, dict) or not isinstance(entry.get("threadId"), str):
            raise RosterInvalidSupervisor(
                "cadena_contexto contiene un elemento que no es un mapping con threadId"
            )
        if entry["threadId"] == orq_thread:
            raise RosterInvalidSupervisor(
                "el orquestador activo ya figura en la cascada de contexto"
            )

    if not supervisor_thread_id.startswith("mcp:"):
        raise RosterInvalidSupervisor(
            "el threadId del supervisor debe tener prefijo mcp:"
        )

    if not supervisor_session_code:
        raise RosterInvalidSupervisor(
            "el session_code del supervisor no puede estar vacio"
        )

    if not isinstance(orq.get("version"), int):
        raise RosterInvalidSupervisor("version del orquestador debe ser int")

    # Supervisor is the predecessor, or an explicit excepcion is provided.
    is_predecessor = supervisor_thread_id == orq.get("predecessor_threadId")
    if excepcion is not None:
        if is_predecessor:
            raise RosterInvalidSupervisor(
                "no se puede pasar excepcion cuando el supervisor "
                "es el predecesor del orquestador"
            )
    elif not is_predecessor:
        raise RosterInvalidSupervisor(
            "el supervisor debe ser el predecesor del orquestador "
            "o proporcionar excepcion con motivo"
        )

    for entry in cascada:
        if entry["threadId"] == supervisor_thread_id:
            raise RosterInvalidSupervisor(
                "el threadId del supervisor ya figura en la cascada de contexto"
            )

    return False


def write_supervisor(  # noqa: C901
    roster_path: Path | str,
    supervisor_thread_id: str,
    supervisor_session_code: str,
    *,
    changes_log_path: Path | str,
    actor: str,
    reason: str,
    excepcion: str | None = None,
    ts: str | None = None,
) -> dict[str, Any]:
    """Rotate supervisor to a new identity, moving old supervisor to cascada.

    Before: roster_path points to a valid JSON roster file.  The roster must
        have active_roles.supervisor and active_roles.orquestador as mappings,
        with the required fields (threadId, session_code, version for supervisor;
        predecessor_threadId for orquestador).  If ts is not None, raises
        ValueError immediately (before reading anything).

    During: normalizes excepcion (empty/whitespace -> absent).  Validates the
        rotation with _validate_rotation (mappings, field types, supervisor !=
        orquestador, orquestador and supervisor absent from cadena_contexto,
        mcp: prefix, non-empty session_code, predecessor-or-excepcion rule),
        first on the initial read and again on EVERY CAS attempt over the
        freshly read state about to be written.  If the requested supervisor
        is already the active one, returns the state unchanged (no-op).
        Builds the new roster:
        updates supervisor with new identity, increments version, sets
        predecessor_threadId to old supervisor, adds old supervisor to
        cadena_contexto at the head (deduplicated by threadId).  If excepcion
        is provided, writes excepcion_supervisor; otherwise removes it.
        Writes atomically with CAS retry (same pattern as write_role_estado).
        Before writing, checks consistency via supervisor_esperado helper.

    After: returns the new roster dict.  The roster file reflects the rotated
        supervisor with incremented version and new cascada head.  One canonical
        log line (supervisor_rotation) is appended.  Raises RosterWriteConflict
        on CAS mismatch.  Raises RosterInvalidSupervisor for validation failures.
    """
    if ts is not None:
        raise ValueError(
            "ts por argumento no es valido; el ts se estampa siempre con el reloj"
        )

    current: dict[str, Any] = _read_roster(roster_path)

    # Normalize excepcion: empty/whitespace -> absent.
    if excepcion is not None:
        excepcion = excepcion.strip()
        if not excepcion:
            excepcion = None

    # Fail fast on the first read; the same validation reruns on every CAS
    # attempt over the freshly read state (see the loop below).
    if _validate_rotation(
        current, supervisor_thread_id, supervisor_session_code, excepcion
    ):
        return current

    # CAS retry loop (same pattern as write_role_estado).
    for attempt in (0, 1):
        if attempt == 1:
            current = _read_roster(roster_path)

        ar = current.get("active_roles")
        if not isinstance(ar, dict):
            raise RosterInvalidSupervisor(
                "active_roles no es un mapping (re-lectura CAS)"
            )

        sup = ar.get("supervisor")
        if not isinstance(sup, dict):
            raise RosterInvalidSupervisor(
                "active_roles.supervisor no es un mapping (re-lectura CAS)"
            )

        orq = ar.get("orquestador")
        if not isinstance(orq, dict):
            raise RosterInvalidSupervisor(
                "active_roles.orquestador no es un mapping (re-lectura CAS)"
            )

        # Re-validate required fields after re-read.
        if "threadId" not in sup or "session_code" not in sup or "version" not in sup:
            raise RosterInvalidSupervisor(
                "missing required fields in active_roles.supervisor (re-lectura CAS)"
            )

        # Use the CAS-fresh supervisor data for old_thread.
        old_thread = sup.get("threadId", "")
        seen_version = sup.get("version", 0)

        # CAS: re-read immediately before writing.
        fresh = _read_roster(roster_path)
        fresh_ar = fresh.get("active_roles")
        if not isinstance(fresh_ar, dict):
            raise RosterInvalidSupervisor(
                "active_roles no es un mapping (CAS pre-write)"
            )
        fresh_sup = fresh_ar.get("supervisor")
        if not isinstance(fresh_sup, dict):
            raise RosterInvalidSupervisor(
                "active_roles.supervisor no es un mapping (CAS pre-write)"
            )
        if fresh_sup.get("version") != seen_version:
            _append_change_line(
                changes_log_path,
                by=actor,
                change="write_conflict",
                detail=(
                    f"supervisor intento={attempt} "
                    f"version_esperada={seen_version} "
                    f"version_real={fresh_sup['version']}"
                ),
                reason=reason,
            )
            if attempt == 1:
                raise RosterWriteConflict(
                    f"conflicto de escritura para supervisor "
                    f"(intento {attempt}: version_esperada={seen_version}, "
                    f"version_real={fresh_sup['version']})"
                )
            if attempt == 0:
                continue

        # Re-validate the DoD 2 closed failures over the state about to be
        # written (a concurrent writer may have changed it without bumping the
        # supervisor version).
        if _validate_rotation(
            fresh, supervisor_thread_id, supervisor_session_code, excepcion
        ):
            return fresh

        # Build new roster.
        new_roster = copy.deepcopy(fresh)
        # Re-read supervisor from CAS-fresh data.
        sup = fresh["active_roles"]["supervisor"]
        old_thread = sup.get("threadId", "")

        # Update supervisor entry.
        new_roster["active_roles"]["supervisor"] = {
            "threadId": supervisor_thread_id,
            "session_code": supervisor_session_code,
            "since": _now_iso(),
            "set_by": actor,
            "predecessor_threadId": old_thread,
            "version": seen_version + 1,
            "status": "active",
        }

        # Update cascada at first level: insert old supervisor at head, deduplicated.
        cascada = [
            e
            for e in (new_roster.get("cadena_contexto") or [])
            if e.get("threadId") != old_thread
        ]
        cascada.insert(
            0,
            {
                "threadId": old_thread,
                "session_code": sup.get("session_code", ""),
                "hasta": _now_iso(),
                "cerrado_por": reason,
            },
        )
        new_roster["cadena_contexto"] = cascada

        # Handle excepcion_supervisor.
        if excepcion is not None:
            new_roster["excepcion_supervisor"] = {
                "coordinadora_threadId": orq.get("threadId", ""),
                "supervisor_threadId": supervisor_thread_id,
                "motivo": excepcion,
                "desde": _now_iso(),
            }
        else:
            new_roster.pop("excepcion_supervisor", None)

        # Consistency check: supervisor matches expected via guard helper.
        if _supervisor_esperado is None:
            raise RosterInvalidSupervisor(
                "no se pudo importar el helper del guard "
                "(check_roster_matches_acting_thread.supervisor_esperado): "
                "el escritor no puede verificar coherencia"
            )

        expected = _supervisor_esperado(new_roster)
        if expected != "indeterminado" and expected != supervisor_thread_id:
            raise RosterInvalidSupervisor(
                f"coheridad escritor-guard: el supervisor esperado es "
                f"'{expected}', no '{supervisor_thread_id}'"
            )

        # Write atomically.
        _atomic_write_json(roster_path, new_roster)

        _append_change_line(
            changes_log_path,
            by=actor,
            change="supervisor_rotation",
            detail=(
                f"supervisor_anterior={old_thread} "
                f"supervisor_nuevo={supervisor_thread_id} "
                f"excepcion={'si' if excepcion else 'no'}"
            ),
            reason=reason,
        )
        return new_roster

    raise RosterWriteConflict("conflicto de escritura para supervisor tras 2 intentos")


def seed_authority_and_rules(
    roster_path: Path | str,
    *,
    actor: str,
    changes_log_path: Path | str,
    reason: str,
) -> dict[str, Any]:
    """Seed session_relief block idempotently, only if authority is present.

    Before: roster_path points to an existing JSON roster file.

    During: if "autoridad" is absent, raises RosterUnknownField immediately
        (the authority block is user-provided, never seeded by the writer).
        If "autoridad" is present but "rules.session_relief" is absent,
        seeds only session_relief.  If both are present, returns unchanged.

    After: returns the (possibly updated) roster dict.  If a change was
        made, a "schema_seed" line is appended mentioning only session_relief.
        Raises RosterUnknownField if authority is absent.
    """
    current: dict[str, Any] = _read_roster(roster_path)

    # Authority must be present: the block is user-provided.
    if "autoridad" not in current:
        raise RosterUnknownField(
            "el bloque autoridad no se siembra automaticamente; "
            "es del usuario y debe proporcionarse"
        )

    # Idempotency gate: session_relief present -> no-op.
    if "session_relief" in current.get("rules", {}):
        return current

    new_roster = copy.deepcopy(current)

    # Add session_relief block only.
    if "session_relief" not in new_roster.get("rules", {}):
        if "rules" not in new_roster:
            new_roster["rules"] = {}
        new_roster["rules"]["session_relief"] = {
            "triaje": {
                "plazo_sin_progreso": 15,
                "sensible_a_causa": "determinista",
            },
            "orquestadora": {
                "plazo_sin_progreso": 10,
                "sensible_a_causa": "determinista",
            },
            "implantacion": {
                "plazo_sin_progreso": 10,
                "sensible_a_causa": "determinista",
            },
        }

    # Write atomically (only if changed).
    _atomic_write_json(roster_path, new_roster)
    _append_change_line(
        changes_log_path,
        by=actor,
        change="schema_seed",
        detail="session_relief incorporado",
        reason=reason,
    )
    return new_roster


# --- CLI ---


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser (flat flags, no subcommands).

    All flags are optional; validation of presence/combinations is done
    in cmd_main, so that conflicts and validation errors return exit code 3
    (not argparse's default 2).
    """
    parser = argparse.ArgumentParser(
        description="Atomic flight roster writer (WOT-2026-136b/136f)."
    )
    parser.add_argument("--roster", default=None, help="Path to flight_roster.json")
    parser.add_argument("--role", default=None, help="Role name in active_roles")
    parser.add_argument(
        "--estado",
        default=None,
        help="New estado (ACTIVO, PENDIENTE_ACK, SALIENTE_MUERTO)",
    )
    parser.add_argument(
        "--changes-log",
        default=None,
        help="Path to roster_changes.jsonl",
    )
    parser.add_argument(
        "--actor",
        default=None,
        help="Actor name (who made the change)",
    )
    parser.add_argument(
        "--reason",
        default=None,
        help="Reason for the change",
    )
    # Rotation flags (WOT-2026-136f).
    parser.add_argument(
        "--supervisor-thread",
        default=None,
        help="threadId of the new supervisor (rotation mode)",
    )
    parser.add_argument(
        "--supervisor-code",
        default=None,
        help="session_code of the new supervisor (rotation mode)",
    )
    parser.add_argument(
        "--excepcion",
        default=None,
        help="Exception reason (rotation mode, optional)",
    )
    return parser


def _validate_flags(args: argparse.Namespace) -> str | None:
    """Validate flag presence and combinations.

    Before: args is a parsed argparse.Namespace.
    During: checks that either (role+estado) or (supervisor_thread+supervisor_code)
        is provided, never both.  Checks that all base flags are present.
        Checks that supervisor_thread and supervisor_code are both present
        when rotation is selected.
    After: returns None if valid, or an error string if invalid.
    """
    has_role = args.role is not None
    has_estado = args.estado is not None
    has_sup_thread = args.supervisor_thread is not None
    has_sup_code = args.supervisor_code is not None

    # Base flags must always be present.
    base_flags_missing = [
        name
        for name, val in [
            ("--roster", args.roster),
            ("--actor", args.actor),
            ("--reason", args.reason),
        ]
        if val is None
    ]
    if base_flags_missing:
        return f"faltan flags base: {', '.join(base_flags_missing)}"

    if args.changes_log is None:
        return "faltan flags base: --changes-log"

    # Determine mode: role-based or rotation.
    has_role_mode = has_role and has_estado
    has_rotation_mode = has_sup_thread or has_sup_code

    # The modes are exclusive even with a partial flag of either side.
    if (has_role or has_estado) and has_rotation_mode:
        return "no se pueden mezclar modos: role/estado y supervisor-thread/supervisor-code son excluyentes"

    # --excepcion belongs to the rotation mode only.
    if args.excepcion is not None and not has_rotation_mode:
        return "--excepcion solo es valido en modo rotacion (--supervisor-thread/--supervisor-code)"

    if has_role_mode:
        # Role mode: estado must be provided.
        if not has_estado:
            return "con --role se requiere --estado"
        return None

    if has_rotation_mode:
        # Rotation mode: both supervisor flags required.
        if not (has_sup_thread and has_sup_code):
            return "con --supervisor-thread se requiere --supervisor-code"
        return None

    return (
        "se requiere un modo: --role/--estado o --supervisor-thread/--supervisor-code"
    )


def cmd_main(args: argparse.Namespace) -> int:
    """CLI entry point: validates flags, calls write_role_estado or write_supervisor."""
    # Validate flag combinations.
    err = _validate_flags(args)
    if err is not None:
        print(err, file=sys.stderr)
        return 3

    try:
        roster_path = Path(args.roster)

        if args.supervisor_thread is not None:
            # Rotation mode (WOT-2026-136f).
            write_supervisor(
                roster_path,
                args.supervisor_thread,
                args.supervisor_code,
                changes_log_path=Path(args.changes_log),
                actor=args.actor,
                reason=args.reason,
                excepcion=args.excepcion,
            )
        else:
            # Role mode (WOT-2026-136b).
            write_role_estado(
                roster_path,
                args.role,
                args.estado,
                changes_log_path=Path(args.changes_log),
                actor=args.actor,
                reason=args.reason,
            )
        return 0
    except RosterWriteConflict as exc:
        print(
            f"{exc}\nconflicto de escritura: {exc}",
            file=sys.stderr,
        )
        return 2
    except (
        RosterInvalidTransition,
        RosterUnknownField,
        RosterRoundTripError,
        RosterInvalidSupervisor,
        RosterMalformed,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 3


def main(argv: list[str] | None = None) -> int:
    """Parse CLI arguments and run cmd_main."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return cmd_main(args)


if __name__ == "__main__":
    sys.exit(main())
