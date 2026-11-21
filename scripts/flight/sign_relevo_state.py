#!/usr/bin/env python3
"""Sign, validate, and select the current handoff state.

Before: receive one of the mutually exclusive state operations and its paths.
During: build or validate the canonical state digest, optionally re-run its
    verification command, and use atomic file replacement for output files.
After: return the contract-defined exit code without consulting live data when
    validating an already signed state.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA = {
    "identidad": ("rol", "hilo"),
    "autoridad": ("runtimeMode", "delivery_authority"),
    "recibo": ("go_fila", "mensaje_id"),
}
DIGEST_FIELDS = (
    "identidad",
    "autoridad",
    "fecha_utc",
    "recibo",
    "comando_verificacion",
    "sha_datos",
)
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_TEXT = "PENDIENTE_RELLENO"
DEFAULT_COMMAND = "python scripts/flight/sign_relevo_state.py --selfcheck"
SCRIPT_ROOT = Path(__file__).resolve().parents[2]


def _digest(state: dict[str, Any]) -> str:
    """Calculate the canonical state digest.

    Before: state contains every field listed in ``DIGEST_FIELDS``.
    During: serialize those fields with the contract's stable JSON settings.
    After: return the lowercase SHA-256 hexadecimal digest.
    """
    payload = json.dumps(
        {key: state[key] for key in DIGEST_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace one output path atomically with exact bytes.

    Before: path names a destination whose parent already exists.
    During: write a temporary sibling file and replace the destination.
    After: the destination contains all bytes or remains unchanged on failure.
    """
    temporary = ""
    try:
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    except (OSError, ValueError):
        if temporary:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
        raise


def _git_sha() -> str:
    """Read and strictly normalize the repository data identifier.

    Before: the process current directory is the repository to sign.
    During: run ``git -C <cwd> rev-parse HEAD`` without shell interpretation.
    After: return exactly forty lowercase hexadecimal characters or raise.
    """
    result = subprocess.run(  # noqa: S603 - contract requires subprocess git
        ["git", "-C", str(Path.cwd()), "rev-parse", "HEAD"],  # noqa: S607
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    value = result.stdout.strip().lower()
    if result.returncode != 0 or not SHA40_RE.fullmatch(value):
        raise ValueError("git rev-parse HEAD no produjo un SHA valido")
    return value


def _state_for_emit(args: argparse.Namespace) -> dict[str, Any]:
    """Build the unsigned fields and attach their repository-bound digest.

    Before: argparse has supplied optional text overrides and an output path.
    During: read the live repository identifier and capture the current UTC time.
    After: return a complete state ready for canonical JSON serialization.
    """
    identidad = {"rol": args.rol, "hilo": args.hilo}
    autoridad = {
        "runtimeMode": args.runtime_mode,
        "delivery_authority": args.delivery_authority,
    }
    recibo = {"go_fila": args.go_fila, "mensaje_id": args.mensaje_id}
    state = {
        "identidad": identidad,
        "autoridad": autoridad,
        "fecha_utc": datetime.utcnow().strftime(DATE_FORMAT),
        "recibo": recibo,
        "comando_verificacion": args.comando,
        "sha_datos": _git_sha(),
    }
    state["sha_estado"] = _digest(state)
    return state


def _read_json(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON object for validation.

    Before: path identifies a candidate state file.
    During: read and decode the complete file as JSON.
    After: return its top-level mapping or raise a read/decode error.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("el estado debe ser un objeto JSON")
    return value


def _schema_ok(state: dict[str, Any]) -> bool:
    """Check required fields and their primitive types.

    Before: state is a decoded JSON mapping.
    During: inspect every required nested field and the command representation.
    After: return true only for a complete, non-empty, single-line schema.
    """
    for section, fields in SCHEMA.items():
        value = state.get(section)
        if not isinstance(value, dict):
            return False
        if any(
            not isinstance(value.get(field), str) or not value[field]
            for field in fields
        ):
            return False
    command = state.get("comando_verificacion")
    if (
        not isinstance(command, str)
        or not command
        or "\n" in command
        or "\r" in command
    ):
        return False
    if not isinstance(state.get("fecha_utc"), str):
        return False
    if not isinstance(state.get("sha_datos"), str):
        return False
    return isinstance(state.get("sha_estado"), str)


def _validate(
    path: Path, *, run_command: bool = True
) -> tuple[int, dict[str, Any] | None]:
    """Validate one state and optionally execute its verification command.

    Before: path points to a purported signed state.
    During: apply the contract's ordered error classes without reading Git.
    After: return zero and the state when valid, otherwise the precise nonzero rc.
    """
    try:
        state = _read_json(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return 10, None
    if not _schema_ok(state):
        return 11, None
    date_value = state["fecha_utc"]
    if not DATE_RE.fullmatch(date_value):
        return 12, None
    try:
        datetime.strptime(date_value, DATE_FORMAT)
    except ValueError:
        return 12, None
    if not SHA40_RE.fullmatch(state["sha_datos"]):
        return 13, None
    if state["sha_estado"] != _digest(state):
        return 14, None
    if run_command and not os.environ.get("SIGN_RELEVO_STATE_VERIFY"):
        environment = os.environ.copy()
        environment["SIGN_RELEVO_STATE_VERIFY"] = "1"
        try:
            result = subprocess.run(  # noqa: S602 - contract requires shell=True
                state["comando_verificacion"],
                shell=True,
                cwd=SCRIPT_ROOT,
                env=environment,
                check=False,
            )
        except (OSError, ValueError):
            return 15, None
        if result.returncode != 0:
            return 15, None
    return 0, state


def _selfcheck() -> int:
    """Check internal schema, regular expressions, and digest sensitivity.

    Before: constants define the signer and verifier contract.
    During: compile regexes, construct a roundtrip fixture, and mutate it.
    After: print the documented marker only when every invariant holds.
    """
    try:
        if tuple(SCHEMA["identidad"]) != ("rol", "hilo"):
            raise ValueError("schema identidad incoherente")
        if set(DIGEST_FIELDS) != {
            "identidad",
            "autoridad",
            "fecha_utc",
            "recibo",
            "comando_verificacion",
            "sha_datos",
        }:
            raise ValueError("campos de digest incoherentes")
        for expression in (DATE_RE, SHA40_RE, SHA64_RE):
            re.compile(expression.pattern)
        fixture = {
            "identidad": {"rol": "r", "hilo": "h"},
            "autoridad": {"runtimeMode": "m", "delivery_authority": "a"},
            "fecha_utc": "2026-01-01T00:00:00Z",
            "recibo": {"go_fila": "g", "mensaje_id": "i"},
            "comando_verificacion": "true",
            "sha_datos": "a" * 40,
        }
        digest = _digest(fixture)
        fixture["sha_estado"] = digest
        if _digest(fixture) != digest:
            raise ValueError("roundtrip de digest roto")
        fixture["recibo"]["go_fila"] = "changed"
        if _digest(fixture) == digest:
            raise ValueError("mutacion no detectada")
    except (TypeError, ValueError, re.error):
        return 1
    print("selfcheck ok")
    return 0


def _parser() -> argparse.ArgumentParser:
    """Create the mutually exclusive command-line parser.

    Before: no arguments have been interpreted.
    During: register the four required operations and their path options.
    After: return an argparse parser ready for ``main``.
    """
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--emit", action="store_true")
    modes.add_argument("--verify")
    modes.add_argument("--selfcheck", action="store_true")
    modes.add_argument("--select-vigente", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--rol", default=DEFAULT_TEXT)
    parser.add_argument("--hilo", default=DEFAULT_TEXT)
    parser.add_argument("--runtime-mode", default=DEFAULT_TEXT)
    parser.add_argument("--delivery-authority", default=DEFAULT_TEXT)
    parser.add_argument("--go-fila", default=DEFAULT_TEXT)
    parser.add_argument("--mensaje-id", default=DEFAULT_TEXT)
    parser.add_argument("--comando", default=DEFAULT_COMMAND)
    return parser


def main(argv: list[str] | None = None) -> int:  # noqa: C901 - CLI dispatch
    """Run one signer operation and return its contract-defined result.

    Before: argv contains a valid request for emit, verify, selfcheck, or select.
    During: dispatch to the operation while translating expected failures to rc.
    After: return an integer suitable for ``SystemExit``.
    """
    args = _parser().parse_args(argv)
    if args.selfcheck:
        return _selfcheck()
    if args.emit:
        if args.out is None:
            return 2
        try:
            state = _state_for_emit(args)
            data = (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode(
                "utf-8"
            )
            _atomic_write(args.out, data)
        except (OSError, ValueError, subprocess.SubprocessError):
            return 1
        return 0
    if args.verify is not None:
        return _validate(Path(args.verify))[0]
    if args.candidates is None or args.out is None:
        return 2
    try:
        candidates = list(args.candidates.glob("*.json"))
    except OSError:
        return 16
    valid: list[tuple[datetime, str, bytes]] = []
    for candidate in candidates:
        rc, state = _validate(candidate)
        if rc == 0 and state is not None:
            try:
                valid.append(
                    (
                        datetime.strptime(state["fecha_utc"], DATE_FORMAT),
                        candidate.name,
                        candidate.read_bytes(),
                    )
                )
            except (OSError, ValueError):
                continue
    if not valid:
        return 16
    latest_date = max(item[0] for item in valid)
    _, _, data = min(
        (item for item in valid if item[0] == latest_date), key=lambda item: item[1]
    )
    try:
        _atomic_write(args.out, data)
    except (OSError, ValueError):
        return 16
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
