#!/usr/bin/env python3
"""Set, clear or inspect the supervisor-authorized stop consultation pause.

Before: the caller provides a flight, roster and acting thread.
During: validates the supervisor identity in a subprocess, writes pause state
atomically and appends the fixed nine-key communications ledger row.
After: only a validated supervisor pause is persisted; all other paths fail
without creating a pause or ledger entry.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_flight(raw: str | None):
    """Before: optional flight path; During: reuses hook topology; After: unique flight or None."""
    hook_path = REPO_ROOT / ".agent" / "hooks" / "native_stop_hook.py"
    import importlib.util

    spec = importlib.util.spec_from_file_location("stop_pause_native_hook", hook_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if raw:
        path = Path(raw).resolve()
        return path if path.is_dir() else None
    flights = module._consult_flights(Path.cwd().resolve())
    return flights[0] if len(flights) == 1 else None


def _parse_now(raw: str | None) -> datetime:
    """Before: optional ISO override; During: parses it; After: returns aware UTC time."""
    if not raw:
        return datetime.now(timezone.utc)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(
        timezone.utc
    )


def _atomic_json(path: Path, data: dict) -> None:
    """Before: target parent is writable; During: writes and replaces temp JSON; After: target is complete or unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


def _check_supervisor(roster: Path, acting_thread: str) -> bool:
    """Before: roster path and acting thread; During: runs canonical identity CLI; After: returns true only on rc 0."""
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "check_roster_matches_acting_thread.py"),
        "--role",
        "supervisor",
        "--roster-path",
        str(roster),
        "--acting-thread",
        acting_thread,
    ]
    try:
        result = subprocess.run(  # noqa: S603
            command, capture_output=True, text=True, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="", file=sys.stderr)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return False
    return True


def _append_ledger(
    flight: Path, acting_thread: str, supervisor_thread: str, consultation: str
) -> None:
    """Before: validated pause action; During: appends exactly the fixed ledger schema; After: one non-legacy JSONL row exists."""
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "by": acting_thread,
        "a": supervisor_thread,
        "modo": "pause",
        "resultado": "pausa_establecida",
        "error": "",
        "providerInstanceId": "",
        "mensaje_id": str(uuid.uuid4()),
        "nota": consultation,
    }
    target = flight / "comms_ledger.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(str(target), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, raw)
    finally:
        os.close(descriptor)


def _set(args: argparse.Namespace) -> int:
    """Before: set arguments are present; During: validates roster, writes pause and ledger; After: returns action status."""
    if args.minutos is None or not 1 <= args.minutos <= 60:
        print("--minutos debe estar entre 1 y 60", file=sys.stderr)
        return 2
    if not args.consulta or not args.acting_thread:
        print("--consulta y --acting-thread son obligatorios", file=sys.stderr)
        return 2
    flight = _load_flight(args.flight_dir)
    if flight is None:
        print("no se pudo resolver un vuelo unico", file=sys.stderr)
        return 1
    roster = (
        Path(args.roster_path).resolve()
        if args.roster_path
        else flight / "flight_roster.json"
    )
    if not _check_supervisor(roster, args.acting_thread):
        print("acting-thread no coincide con supervisor", file=sys.stderr)
        return 1
    try:
        data = json.loads(roster.read_text(encoding="utf-8-sig"))
        supervisor = data["active_roles"]["supervisor"]
        version = supervisor["version"]
        supervisor_thread = supervisor["threadId"]
        if not isinstance(supervisor_thread, str):
            raise ValueError("supervisor.threadId invalido")
        now = _parse_now(args.now)
        _atomic_json(
            flight / "stop_consult_pause.json",
            {
                "hasta": (now + timedelta(minutes=args.minutos)).isoformat(),
                "epoca": str(version),
                "supervisor_threadId": supervisor_thread,
                "set_at": now.isoformat(),
                "minutos": args.minutos,
                "consulta": args.consulta,
                "acting_thread": args.acting_thread,
            },
        )
        _append_ledger(flight, args.acting_thread, supervisor_thread, args.consulta)
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError) as exc:
        print(f"no se pudo establecer pausa: {exc}", file=sys.stderr)
        return 1
    print("stop_consult_pause: establecida")
    return 0


def _clear(args: argparse.Namespace) -> int:
    """Before: optional flight; During: removes pause idempotently; After: rc 0 even when absent."""
    flight = _load_flight(args.flight_dir)
    if flight is None:
        return 0
    try:
        (flight / "stop_consult_pause.json").unlink(missing_ok=True)
    except OSError as exc:
        print(f"no se pudo borrar pausa: {exc}", file=sys.stderr)
        return 1
    print("stop_consult_pause: off")
    return 0


def _status(args: argparse.Namespace) -> int:
    """Before: optional flight; During: reads pause state only; After: prints vigente/ausente with rc 0."""
    flight = _load_flight(args.flight_dir)
    if flight is None:
        print("stop_consult_pause: ausente")
        return 0
    target = flight / "stop_consult_pause.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        until = datetime.fromisoformat(str(data["hasta"]).replace("Z", "+00:00"))
        until = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        vigente = datetime.now(timezone.utc) < until.astimezone(timezone.utc)
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError):
        vigente = False
    print("stop_consult_pause: vigente" if vigente else "stop_consult_pause: ausente")
    return 0


def _parser() -> argparse.ArgumentParser:
    """Before: no arguments; During: builds mutually exclusive lifecycle flags; After: parser is ready."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--set", action="store_true")
    actions.add_argument("--clear", action="store_true")
    actions.add_argument("--status", action="store_true")
    parser.add_argument("--minutos", type=int)
    parser.add_argument("--consulta")
    parser.add_argument("--acting-thread")
    parser.add_argument("--flight-dir")
    parser.add_argument("--roster-path")
    parser.add_argument("--now")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: CLI arguments; During: dispatches set/clear/status; After: returns rc."""
    args = _parser().parse_args(argv)
    if args.set:
        return _set(args)
    if args.clear:
        return _clear(args)
    return _status(args)


if __name__ == "__main__":
    raise SystemExit(main())
