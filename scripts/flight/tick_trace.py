"""Append one structured record for each coordinator heartbeat.

Before: the caller supplies an existing absolute ``--ops-dir`` and explicit
measurements; no live flight files are read.
During: validate the arguments, build schema version 1, and append one UTF-8
JSON line to the fixed ``tick_trace.jsonl`` path with one binary write;
``quota_summary`` is bounded to 200 characters.
After: return 0 for a fully measured record, 1 for a record containing null
measurements, or 2 for usage/I/O errors, always with a named stdout message.

Threat model: confia en el ops-dir; no defiende frente a un enlace simbolico
plantado por quien ya puede escribir ahi.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any


TRACE_NAME = "tick_trace.jsonl"
FIELDS = (
    "coordinator",
    "roster_sha12",
    "guard_rc",
    "quota_rc",
    "quota_summary",
)
_SHA12 = re.compile(r"[0-9a-fA-F]{12}")
_TS_WITH_OFFSET = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


class UsageError(ValueError):
    """Raised when a command-line value violates the trace contract."""


def _parser() -> argparse.ArgumentParser:
    """Build the CLI parser without defaults that could write implicitly.

    Before: no state is required.
    During: declare the mandatory output directory and explicit measurements.
    After: return a parser whose values can be validated before any I/O.
    """
    parser = argparse.ArgumentParser(
        description="Append one coordinator heartbeat trace record",
    )
    parser.add_argument("--ops-dir", required=True)
    parser.add_argument("--coordinator")
    parser.add_argument("--roster-sha12")
    parser.add_argument("--guard-rc")
    parser.add_argument("--quota-rc")
    parser.add_argument("--quota-summary")
    parser.add_argument("--ts")
    parser.add_argument("--unmeasured", action="append", default=[])
    return parser


def _parse_rc(raw: str | None, field: str) -> int | None:
    """Parse an optional integer measurement.

    Before: ``raw`` is either absent or the literal argument value.
    During: convert only base-10 integer text.
    After: return an integer or null; raise ``UsageError`` for invalid text.
    """
    if raw is None:
        return None
    try:
        return int(raw, 10)
    except (TypeError, ValueError) as exc:
        raise UsageError(f"{field} must be an integer") from exc


def _parse_unmeasured(values: list[str]) -> dict[str, str]:
    """Parse repeatable field-reason declarations.

    Before: each value has the form ``FIELD=REASON``.
    During: validate the field against the fixed schema and preserve the
    reason verbatim after the separator.
    After: return one reason per field or raise ``UsageError``.
    """
    reasons: dict[str, str] = {}
    for value in values:
        field, separator, reason = value.partition("=")
        if not separator or field not in FIELDS or not reason:
            raise UsageError("--unmeasured must be FIELD=RAZON for a known field")
        reasons[field] = reason
    return reasons


def _parse_ts(raw: str | None) -> str:
    """Return an offset-bearing ISO-8601 timestamp with seconds.

    Before: ``raw`` is absent or a caller-supplied timestamp.
    During: use the local aware clock for omission, otherwise parse and verify
    timezone information and preserve the supplied representation.
    After: return a valid timestamp string or raise ``UsageError``.
    """
    if raw is None:
        return dt.datetime.now().astimezone().isoformat(timespec="seconds")
    if not _TS_WITH_OFFSET.fullmatch(raw):
        raise UsageError("ts must be ISO8601 with an offset and seconds")
    try:
        dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UsageError("ts must be ISO8601 with an offset and seconds") from exc
    return raw


def _record(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Validate explicit inputs and build a JSON-serializable record.

    Before: parser values exist but no output path has been opened.
    During: validate directory, hashes, return codes, timestamp and reasons;
    assign null plus a reason to every omitted measurement. An empty
    ``quota_summary`` is treated as measured and therefore returns rc 0.
    After: return the record and its semantic rc (0 measured or 1 degraded).
    """
    raw_ops = str(args.ops_dir)
    ops_dir = Path(raw_ops)
    if not ops_dir.is_absolute() or not ops_dir.is_dir():
        raise UsageError("ops-dir must be an existing absolute directory")
    if args.roster_sha12 is not None and not _SHA12.fullmatch(args.roster_sha12):
        raise UsageError("roster-sha12 must be exactly 12 hexadecimal characters")
    guard_rc = _parse_rc(args.guard_rc, "guard-rc")
    quota_rc = _parse_rc(args.quota_rc, "quota-rc")
    reasons = _parse_unmeasured(args.unmeasured)
    timestamp = _parse_ts(args.ts)
    record: dict[str, Any] = {
        "v": 1,
        "ts": timestamp,
        "coordinator": args.coordinator,
        "roster_sha12": args.roster_sha12,
        "guard_rc": guard_rc,
        "quota_rc": quota_rc,
        "quota_summary": (
            args.quota_summary[:200] if args.quota_summary is not None else None
        ),
        "unmeasured": {},
    }
    for field in FIELDS:
        if record[field] is None:
            record["unmeasured"][field] = reasons.get(field, "not_provided")
    return record, int(bool(record["unmeasured"]))


def _append(ops_dir: Path, record: dict[str, Any]) -> None:
    """Append one complete JSONL payload to the fixed trace file.

    Before: ``ops_dir`` is an existing directory and ``record`` is validated.
    During: inspect the existing final byte, prepend LF when needed, and issue
    one ``write`` call in binary append mode to the fixed child path.
    After: the new JSON object ends in LF; ``OSError`` propagates to ``main``.
    """
    target = ops_dir / TRACE_NAME
    prefix = b""
    if target.exists():
        if not target.is_file():
            raise OSError(f"trace path is not a file: {target}")
        previous = target.read_bytes()
        if previous and previous[-1:] != b"\n":
            prefix = b"\n"
    payload = prefix + (
        json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    with target.open("ab") as handle:
        handle.write(payload)


def main(argv: list[str] | None = None) -> int:
    """Run the trace command and convert expected failures to named rc output.

    Before: ``argv`` is absent or a command-line argument list.
    During: parse and validate without opening or writing the trace file, append only after validation, and
    catch usage/I/O errors so heartbeat callers never receive a traceback.
    After: print exactly one ``TICK_TRACE`` status line and return 0, 1 or 2;
    argparse ``--help`` intentionally exits with SystemExit(0) without a
    ``TICK_TRACE`` status line.
    """
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        record, rc = _record(args)
        _append(Path(args.ops_dir), record)
    except (argparse.ArgumentError, OSError, UsageError, ValueError) as exc:
        print(f"TICK_TRACE error {exc}")
        return 2
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        print("TICK_TRACE error invalid arguments")
        return 2
    status = "degraded" if rc else "ok"
    print(f"TICK_TRACE {status} {TRACE_NAME}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
