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


# --- Private helpers ---


def _read_roster(path: Path | str) -> dict[str, Any]:
    """Read and parse roster JSON.

    Before: path points to a valid JSON file.
    During: reads the file with utf-8 encoding and parses JSON.
    After: returns the top-level dict.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


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

    # Validate role exists in active_roles.
    if role not in current["active_roles"] or role == "_schema_note":
        raise RosterUnknownField(f"rol desconocido: {role}")

    old_estado: str | None = current["active_roles"][role].get("estado")

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

        seen_version = current["active_roles"][role]["version"]

        # Validate transition against the state read in this attempt.
        current_old = current["active_roles"][role].get("estado")

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
        if fresh["active_roles"][role]["version"] != seen_version:
            _append_change_line(
                changes_log_path,
                by=actor,
                change="write_conflict",
                detail=(
                    f"role={role} intento={attempt} "
                    f"version_esperada={seen_version} "
                    f"version_real={fresh['active_roles'][role]['version']}"
                ),
                reason=reason,
            )
            if attempt == 1:
                raise RosterWriteConflict(
                    f"conflicto de escritura para {role} "
                    f"(intento {attempt}: version_esperada={seen_version}, "
                    f"version_real={fresh['active_roles'][role]['version']})"
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


def seed_authority_and_rules(
    roster_path: Path | str,
    *,
    actor: str,
    changes_log_path: Path | str,
    reason: str,
) -> dict[str, Any]:
    """Idempotently seed authority and session_relief blocks in the roster.

    Before: roster_path points to an existing JSON roster file.

    During: if both "autoridad" and "rules.session_relief" are already
        present, returns the roster unchanged (idempotency).  Otherwise,
        adds the authority object with 5 decision authorities + nota,
        and the session_relief dict with three slots (triaje, orquestadora,
        implantacion).  Does NOT touch active_roles, sessions, or
        roster_fixes.  Writes atomically only if there was a real change.

    After: returns the (possibly updated) roster dict.  If a change was
        made, a "schema_seed" line is appended to the changes log.
    """
    current: dict[str, Any] = _read_roster(roster_path)

    # Idempotency gate: both blocks present -> no-op.
    if "autoridad" in current and "session_relief" in current.get("rules", {}):
        return current

    new_roster = copy.deepcopy(current)

    # Add authority block (6 fields, exact literal from session_registry.json).
    if "autoridad" not in new_roster:
        new_roster["autoridad"] = {
            "merge": "SUPERVISOR-2",
            "push": "SUPERVISOR-2",
            "suite_canonica": "SUPERVISOR-2",
            "admision_ticket_nuevo": "SUPERVISOR-2",
            "backends_retirados": "SUPERVISOR-2",
            "nota": "la autoridad no se hereda por posicion en la cadena; fuente: roster active_roles.supervisor",
        }

    # Add session_relief block.
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
        detail="autoridad y session_relief incorporados",
        reason=reason,
    )
    return new_roster


# --- CLI ---


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser (flat flags, no subcommands)."""
    parser = argparse.ArgumentParser(
        description="Atomic flight roster writer (WOT-2026-136b)."
    )
    parser.add_argument("--roster", required=True, help="Path to flight_roster.json")
    parser.add_argument("--role", required=True, help="Role name in active_roles")
    parser.add_argument(
        "--estado",
        required=True,
        help="New estado (ACTIVO, PENDIENTE_ACK, SALIENTE_MUERTO)",
    )
    parser.add_argument(
        "--changes-log",
        required=True,
        help="Path to roster_changes.jsonl",
    )
    parser.add_argument(
        "--actor",
        required=True,
        help="Actor name (who made the change)",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Reason for the change",
    )
    return parser


def cmd_main(args: argparse.Namespace) -> int:
    """CLI entry point: calls write_role_estado, maps exceptions to exit codes."""
    try:
        write_role_estado(
            Path(args.roster),
            args.role,
            args.estado,
            changes_log_path=Path(args.changes_log),
            actor=args.actor,
            reason=args.reason,
        )
        return 0
    except RosterWriteConflict as exc:
        print(
            f"{exc}\nESCALAR A SUPERVISOR-2: {exc}",
            file=sys.stderr,
        )
        return 2
    except (
        RosterInvalidTransition,
        RosterUnknownField,
        RosterRoundTripError,
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
