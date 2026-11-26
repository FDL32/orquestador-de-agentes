#!/usr/bin/env python3
"""Manage the WOT-2026-215b stop-consult mode for one flight.

Before: a flight directory is supplied or uniquely discoverable from the hook.
During: reads counters and writes mode JSON atomically, never touching a
transcript. After: reports the requested state and an explicit exit code.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODES = frozenset({"off", "observe", "canary", "block"})


def _load_hook():
    """Before: hook path exists; During: imports the shared topology helpers; After: returns module or raises."""
    path = REPO_ROOT / ".agent" / "hooks" / "native_stop_hook.py"
    spec = importlib.util.spec_from_file_location("stop_consult_native_hook", path)
    if spec is None or spec.loader is None:
        raise ImportError("no se pudo cargar native_stop_hook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flight_dir(raw: str | None):
    """Before: optional directory; During: resolves explicit or unique flight; After: Path or None."""
    hook = _load_hook()
    if raw:
        path = Path(raw).resolve()
        return path if path.is_dir() else None
    flights = hook._consult_flights(Path.cwd().resolve())
    return flights[0] if len(flights) == 1 else None


def _atomic_json(path: Path, data: dict) -> None:
    """Before: target parent is writable; During: replaces a UTF-8 temp file; After: one newline-terminated JSON file exists."""
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


def _read_mode(flight: Path) -> str:
    """Before: flight directory; During: reads mode JSON tolerantly; After: returns one of four modes, defaulting off."""
    try:
        data = json.loads(
            (flight / "stop_consult_mode.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return "off"
    mode = data.get("mode") if isinstance(data, dict) else None
    return mode if mode in MODES else "off"


def _parse_now(raw: str | None) -> datetime:
    """Before: optional ISO timestamp; During: parses it; After: returns aware UTC now or override."""
    if not raw:
        return datetime.now(timezone.utc)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(
        timezone.utc
    )


def _on(args: argparse.Namespace) -> int:
    """Before: valid mode arguments; During: atomically writes mode; After: rc 0 or no write on validation/error."""
    if args.mode not in MODES:
        print("modo invalido", file=sys.stderr)
        return 2
    if args.mode == "canary" and not isinstance(args.canary_token, str):
        print("canary exige --canary-token", file=sys.stderr)
        return 2
    flight = _flight_dir(args.flight_dir)
    if flight is None:
        print("no se pudo resolver un vuelo unico", file=sys.stderr)
        return 1
    try:
        _atomic_json(
            flight / "stop_consult_mode.json",
            {
                "mode": args.mode,
                "canary_token": args.canary_token,
                "set_at": _parse_now(args.now).isoformat(),
                "set_by": "stop_consult_mode",
            },
        )
    except OSError as exc:
        print(f"no se pudo escribir el modo: {exc}", file=sys.stderr)
        return 1
    print(f"stop_consult_mode: {args.mode}")
    return 0


def _status(args: argparse.Namespace) -> int:  # noqa: C901
    """Before: optional flight and report flag; During: reads state/counters; After: prints status with rc."""
    flight = _flight_dir(args.flight_dir)
    if flight is None:
        if args.report:
            print(
                json.dumps(
                    {
                        "modo": "off",
                        "no_medido": 0,
                        "topes": 0,
                        "escapes": 0,
                        "ventana_h": 24,
                        "rc": 1,
                    }
                )
            )
            return 1
        print("stop_consult_mode: off")
        return 0
    mode = _read_mode(flight)
    if not args.report:
        print(f"stop_consult_mode: {mode}")
        return 0
    now = _parse_now(args.now)
    counts = {"no_medido": 0, "topes": 0, "escapes": 0}
    rc = 0
    try:
        raw = (flight / "stop_consult_observations.jsonl").read_text(encoding="utf-8")
        for line in raw.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            stamp = datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00"))
            stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            if (
                now - stamp.astimezone(timezone.utc) > timedelta(hours=24)
                or stamp > now
            ):
                continue
            if row.get("decision") == "no_medido":
                counts["no_medido"] += 1
            if row.get("decision") == "tope":
                counts["topes"] += 1
            if row.get("motivo") == "escape_segundo_cierre":
                counts["escapes"] += 1
    except FileNotFoundError:
        pass
    except (OSError, UnicodeDecodeError, ValueError, TypeError, KeyError):
        rc = 1
    print(
        json.dumps(
            {"modo": mode, **counts, "ventana_h": 24, "rc": rc}, ensure_ascii=False
        )
    )
    return rc


def _build_parser() -> argparse.ArgumentParser:
    """Before: no arguments; During: builds CLI parser; After: parser accepts mode lifecycle commands."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("on", "off", "status"))
    parser.add_argument("--mode", choices=sorted(MODES), default=None)
    parser.add_argument("--canary-token", default=None)
    parser.add_argument("--flight-dir", default=None)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--now", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Before: argv is CLI input; During: dispatches lifecycle command; After: returns its rc."""
    args = _build_parser().parse_args(argv)
    if args.action == "on":
        if args.mode is None:
            print("on exige --mode", file=sys.stderr)
            return 2
        return _on(args)
    if args.action == "off":
        args.mode = "off"
        return _on(args)
    return _status(args)


if __name__ == "__main__":
    raise SystemExit(main())
